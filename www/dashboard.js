"use strict";
const $ = id => document.getElementById(id);
const FAN_MAX_RPM = 1500;
const state = {online:false, busy:false, manual:null, lastSent:0, status:null, controlEpoch:0,
  boot:null, rows:new Map(), historyMinute:null, historyLoaded:false, offset:0,
  curve:null, curveLoaded:false, curveBusy:false, curveDirty:false, nextCurveLoad:0,
  automatic:null};
const charts = [
  {name:"temperature", title:"temperature", columns:[2,3], csv:["gpu_temperature_c","cpu_temperature_c"], colors:["#157c9b","#cb5a5a"], labels:["GPU","CPU"], unit:"\u00b0C", max:100},
  {name:"rpm", title:"estimated RPM", columns:[1], csv:["estimated_rpm"], colors:["#277a48"], labels:["Estimated fan"], unit:"RPM", max:FAN_MAX_RPM},
  {name:"pwm", title:"PWM", columns:[4], csv:["applied_pwm_percent"], colors:["#735b9f"], labels:["PWM"], unit:"%", max:100}
];
const chartRanges = {
  all:{label:"All retained data",minutes:null},
  "24h":{label:"Last 24 hours",minutes:1440},
  "12h":{label:"Last 12 hours",minutes:720},
  "3h":{label:"Last 3 hours",minutes:180},
  "1h":{label:"Last hour",minutes:60},
  "30m":{label:"Last 30 minutes",minutes:30},
  "15m":{label:"Last 15 minutes",minutes:15}
};
let queue = Promise.resolve();
let expandedChart = null;
let expandedRange = "all";
function request(path, body) {
  const task = queue.then(async () => {
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 6000);
    try {
      const headers = {};
      if (body !== undefined) {
        headers["Content-Type"] = "application/json";
      }
      const response = await fetch(path, {method:body === undefined ? "GET" : "POST",
        headers, body:body === undefined ? undefined : JSON.stringify(body),
        signal:abort.signal, cache:"no-store"});
      if (!response.ok) {
        if(response.status===401)location.replace("/login");
        const error = new Error("Request failed (" + response.status + ")");
        error.status = response.status;
        throw error;
      }
      return await response.json();
    } finally { clearTimeout(timeout); }
  });
  queue = task.catch(() => {});
  return task;
}
function message(text, error=false) {
  $("control-message").textContent = text;
  $("control-message").classList.toggle("error", error);
}
function controls() {
  const locked = !state.online || state.busy;
  const automatic = state.automatic === true;
  for (const id of ["apply","off","full"]) $(id).disabled = locked || automatic;
  $("release").disabled = locked || automatic || state.manual === null;
  $("hold-state").textContent = automatic ? "Temperature curve active" :
    state.manual === null ? "Browser hold inactive" : "Browser hold active";
  const valid=readCurve()!==null;
  $("curve-apply").disabled=locked || state.curveBusy || !valid;
  $("curve-download").disabled=!valid;
  $("curve-discard").disabled=!state.curveLoaded || state.curveBusy || !state.curveDirty;
  $("curve-add").disabled=!valid || $("curve-steps").children.length>=8;
  $("curve-toggle").disabled=locked || state.curveBusy || !state.curveLoaded;
  $("curve-toggle").textContent=automatic ? "Pause automatic control" : "Activate temperature curve";
  $("curve-toggle").classList.toggle("primary",!automatic);
  $("curve-state").textContent=automatic ? "Automatic control active" : "Automatic control paused";
}
function fmt(value, digits=0) { return value == null ? "--" : Number(value).toLocaleString(undefined, {maximumFractionDigits:digits}); }
function estimatedRpm(duty) {
  if (duty == null || !Number.isFinite(Number(duty))) return null;
  return Math.round(Math.min(100, Math.max(0, Number(duty))) * FAN_MAX_RPM / 100);
}
function renderStatus(data) {
  if (state.boot !== data.boot_id) {
    if (state.boot !== null) { state.manual = null; message("Controller restarted; hold released"); }
    state.boot = data.boot_id;
    state.rows.clear(); state.historyMinute = null; state.historyLoaded = false;
    state.curveLoaded=false;state.nextCurveLoad=0;
  }
  state.status = data; state.online = true;
  if(typeof data.automatic_control_active==="boolean")state.automatic=data.automatic_control_active;
  state.offset = Date.now() - data.now_seconds * 1000;
  document.body.classList.remove("offline");
  $("connection").textContent = "Connected"; $("connection").className = "badge live";
  $("last-seen").textContent = "Updated " + new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"});
  const rpm=estimatedRpm(data.applied_duty);
  $("rpm").textContent = fmt(rpm); $("pwm").textContent = fmt(data.applied_duty,1);
  $("curve-rpm").textContent="Estimated fan speed "+fmt(rpm)+" RPM";
  $("gpu").textContent = fmt(data.gpu_temperature_c,1); $("cpu").textContent = fmt(data.cpu_temperature_c,1);
  $("rpm-state").textContent = "Linear estimate from PWM / "+fmt(FAN_MAX_RPM)+" RPM max";
  const names = {awaiting_command:"Awaiting command", startup:"Startup boost", standalone:"Standalone",
    controlled:"Controlled", command_timeout:"Command timeout / full speed", wifi_disconnected:"Wi-Fi lost / full speed",
    network_error:"Network error / full speed", configuration_error:"Configuration fallback",
    automatic_starting:"Automatic control starting / full speed",
    automatic_disabled:"Automatic control paused / full speed"};
  $("fan-state").textContent = data.startup_boost ? "Startup boost" : names[data.state] || data.state;
  for (const sensor of ["gpu", "cpu"]) {
    $(sensor+"-state").textContent = data.telemetry_state === "live" ?
      (data[sensor+"_temperature_c"] == null ? "Sensor unavailable" : "Updated " + data.telemetry_age_seconds + "s ago") :
      data.telemetry_state === "stale" ? "Telemetry stale" : "No telemetry";
  }
  $("timeout").textContent = "Command timeout: " + data.command_timeout_seconds + "s";
  $("uptime").textContent = "Controller uptime " + Math.floor(data.uptime_seconds / 3600) + "h " + Math.floor(data.uptime_seconds / 60) % 60 + "m";
  if (state.manual !== null && (data.state !== "controlled" || data.requested_duty !== state.manual)) {
    state.manual = null; message("Hold ended; controller state changed");
  }
  controls();
}
async function command(duty) {
  if (state.busy) return;
  const epoch = state.controlEpoch;
  state.busy = true; controls();
  try {
    const data = await request("/api/fan", {duty});
    renderStatus(data);
    if (epoch !== state.controlEpoch || document.hidden) {
      state.manual = null; message("Hold canceled; full-speed fallback at command timeout"); return;
    }
    state.manual = duty; state.lastSent = Date.now();
    message(duty === 0 ? "Off requested; browser hold active" : "Holding " + duty + "% PWM");
  } catch (error) {
    state.manual = null;
    message(error.message + "; output unconfirmed. Full-speed fallback at command timeout.", true);
  } finally { state.busy = false; controls(); }
}
async function release() {
  state.manual = null; state.busy = true; controls();
  try { renderStatus(await request("/api/release", {})); message("Hold released; full speed requested"); }
  catch (error) { message(error.message + "; full-speed fallback at command timeout", true); }
  finally { state.busy = false; controls(); }
}
async function history() {
  const minute = Math.floor(state.status.now_seconds / 60);
  if (state.historyMinute === minute) return;
  const boot = state.boot;
  let before = null;
  do {
    const page = await request("/api/history" + (before === null ? "" : "?before=" + before));
    if (page.boot_id !== boot) { state.historyMinute = null; return; }
    for (const row of page.rows) {
      const displayed=[...row];displayed[1]=estimatedRpm(displayed[4]);
      state.rows.set(displayed[0], displayed);
    }
    before = state.historyLoaded ? null : page.next_before;
  } while (before !== null);
  for (const key of state.rows.keys()) if (key < minute - 1439) state.rows.delete(key);
  state.historyMinute = minute; state.historyLoaded = true;
  $("history-state").textContent = state.rows.size.toLocaleString() + " / 1,440 minutes retained since restart";
  drawCharts();
}
function drawCharts() {
  charts.forEach(chart => drawChart(chart)); drawCurve();
  if($("history-dialog").open && expandedChart){
    drawChart(expandedChart,null,"expanded");
    $("history-export").disabled=!rangeRows(expandedChart).length;
  }
}
function agoLabel(minutes){
  if(minutes<60)return Math.max(1,Math.round(minutes))+" min";
  const hours=minutes/60;
  return (hours>=10 ? Math.round(hours) : Math.round(hours*10)/10)+" h";
}
function drawChart(chart, hover=null, target=chart.name) {
  const canvas = $(target + "-chart");
  const box = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(box.width * ratio); canvas.height = Math.round(box.height * ratio);
  const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio);
  const w = box.width, h = box.height, left=43, right=12, top=10, bottom=26;
  const width = w-left-right, height=h-top-bottom;
  const end = state.status ? state.status.now_seconds/60 : 0;
  const allRows = [...state.rows.values()].sort((a,b) => a[0]-b[0]);
  const selectedMinutes=target==="expanded" ? chartRanges[expandedRange].minutes : 1440;
  const firstMinute=allRows.length ? allRows[0][0] : end-1;
  const start=selectedMinutes===null ? Math.min(firstMinute,end-1) : end-selectedMinutes;
  const span=Math.max(1,end-start);
  const rows=allRows.filter(row=>row[0]>=start && row[0]<=end);
  let max=chart.max, min=0, present=false;
  for (const row of rows) for (const column of chart.columns) if (row[column] !== null) {
    max=Math.max(max, Math.ceil(row[column]/20)*20); min=Math.min(min, Math.floor(row[column]/20)*20); present=true;
  }
  const x = minute => left+(minute-start)/span*width;
  const y = value => top+(max-value)/(max-min)*height;
  ctx.font="10px system-ui"; ctx.lineWidth=1;
  for(let tick=0;tick<=4;tick++) {
    const value=min+(max-min)*tick/4, py=y(value);
    ctx.strokeStyle="#e2e7e4";ctx.beginPath();ctx.moveTo(left,py);ctx.lineTo(w-right,py);ctx.stroke();
    ctx.fillStyle="#728078";ctx.textAlign="right";ctx.fillText(fmt(value),left-8,py+3);
  }
  for(let tick=0;tick<=4;tick++) {
    ctx.textAlign=tick===0 ? "left" : tick===4 ? "right" : "center";
    ctx.fillText(tick===4 ? "Now" : "−"+agoLabel(span*(4-tick)/4),left+tick*width/4,h-5);
  }
  ctx.save();ctx.beginPath();ctx.rect(left,top,width,height);ctx.clip();
  chart.columns.forEach((column,index) => {
    ctx.strokeStyle=chart.colors[index]; ctx.fillStyle=chart.colors[index];ctx.lineWidth=1.7;
    ctx.beginPath();let previous=null;
    for(const row of rows) {
      if(row[column] === null) {previous=null;continue;}
      const px=x(row[0]),py=y(row[column]);
      if(previous === null || row[0]-previous>1) ctx.moveTo(px,py); else ctx.lineTo(px,py);
      previous=row[0];
    }
    ctx.stroke();
    for(const row of rows) if(row[column] !== null) {ctx.beginPath();ctx.arc(x(row[0]),y(row[column]),1.2,0,Math.PI*2);ctx.fill();}
  });
  if(hover !== null) {ctx.strokeStyle="#88988e";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(hover,top);ctx.lineTo(hover,h-bottom);ctx.stroke();}
  ctx.restore();
  $(target+"-empty").hidden=present;
  let row=rows.at(-1);
  if(hover !== null) row=state.rows.get(Math.round(start+(hover-left)/width*span));
  const readout=$(target+"-readout");
  if(row) {
    const date=new Date(row[0]*60000+state.offset);
    readout.textContent=date.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})+"  |  "+chart.columns.map((column,index)=>chart.labels[index]+" "+fmt(row[column],1)+" "+chart.unit).join("  /  ");
  } else readout.textContent=hover !== null ? "No sample for this minute" : "No samples yet";
}
async function poll() {
  try {
    const data = await request("/api/dashboard");
    renderStatus(data);
    if(!state.curveLoaded && Date.now()>=state.nextCurveLoad)await loadCurve();
    if (state.manual !== null && !document.hidden && Date.now()-state.lastSent >= Math.min(5000,data.command_timeout_seconds*1000/3)) await command(state.manual);
    await history();
  } catch (error) {
    state.online=false; state.manual=null;
    document.body.classList.add("offline");
    $("connection").textContent="Disconnected"; $("connection").className="badge error";
    $("history-state").textContent="Connection interrupted; retained samples shown";
    message("Connection lost; full-speed fallback at command timeout",true); controls();
  } finally { setTimeout(poll, 2000); }
}
$("speed").addEventListener("input",()=>{$("speed-label").textContent=$("speed").value+"%";});
$("apply").addEventListener("click",()=>command(Number($("speed").value)));
$("full").addEventListener("click",()=>command(100));
$("off").addEventListener("click",()=>command(0));
$("release").addEventListener("click",release);
$("logout").addEventListener("click",async()=>{
  try{await request("/api/logout",{});}finally{location.replace("/login");}
});
document.addEventListener("visibilitychange",()=>{
  if(document.hidden)state.controlEpoch++;
  if(document.hidden && state.manual!==null){state.manual=null;controls();message("Browser hold paused; full-speed fallback at command timeout");}
});
for(const chart of charts) {
  const canvas=$(chart.name+"-chart");
  canvas.addEventListener("pointermove",event=>drawChart(chart,event.clientX-canvas.getBoundingClientRect().left));
  canvas.addEventListener("pointerleave",()=>drawChart(chart));
}
new ResizeObserver(drawCharts).observe(document.querySelector(".history"));
new ResizeObserver(()=>{if(expandedChart && $("history-dialog").open)drawChart(expandedChart,null,"expanded");}).observe($("expanded-panel"));
function selectExpanded(name){
  expandedChart=charts.find(chart=>chart.name===name);
  for(const tab of document.querySelectorAll(".chart-tabs [role=tab]")){
    const selected=tab.dataset.chart===name;tab.setAttribute("aria-selected",String(selected));tab.tabIndex=selected ? 0 : -1;
  }
  $("expanded-panel").setAttribute("aria-labelledby","tab-"+name);
  $("expanded-chart").setAttribute("aria-label",$(name+"-chart").getAttribute("aria-label"));
  $("expanded-empty").textContent=$(name+"-empty").textContent;
  $("expanded-legend").replaceChildren($(name+"-chart").closest("figure").querySelector(".legend").cloneNode(true));
  const exportButton=$("history-export");
  exportButton.disabled=!rangeRows(expandedChart).length;
  exportButton.setAttribute("aria-label","Export "+expandedChart.title+" chart data as CSV");
  drawChart(expandedChart,null,"expanded");
}
function exportableRows(chart){
  return [...state.rows.values()].filter(row=>chart.columns.some(column=>row[column]!==null)).sort((a,b)=>a[0]-b[0]);
}
function rangeRows(chart){
  const rows=exportableRows(chart),minutes=chartRanges[expandedRange].minutes;
  if(minutes===null || !state.status)return rows;
  const start=state.status.now_seconds/60-minutes;
  return rows.filter(row=>row[0]>=start);
}
function exportHistory(){
  if(!expandedChart)return;
  const rows=rangeRows(expandedChart);if(!rows.length)return;
  const lines=[["timestamp",...expandedChart.csv].join(",")];
  for(const row of rows){
    const timestamp=new Date(row[0]*60000+state.offset).toISOString();
    lines.push([timestamp,...expandedChart.columns.map(column=>row[column]===null ? "" : row[column])].join(","));
  }
  const url=URL.createObjectURL(new Blob([lines.join("\n")+"\n"],{type:"text/csv"}));
  const link=document.createElement("a");link.href=url;link.download="dgx-fan-"+expandedChart.name+"-"+new Date().toISOString().slice(0,10)+".csv";link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
for(const button of document.querySelectorAll("[data-expand]"))button.addEventListener("click",()=>{
  $("history-dialog").showModal();document.body.classList.add("modal-open");selectExpanded(button.dataset.expand);
});
function selectRange(name){
  if(!chartRanges[name])return;
  expandedRange=name;
  for(const button of document.querySelectorAll("[data-range]"))button.setAttribute("aria-pressed",String(button.dataset.range===name));
  $("range-summary").textContent=chartRanges[name].label+" / 1-minute samples";
  if(expandedChart){
    $("history-export").disabled=!rangeRows(expandedChart).length;
    drawChart(expandedChart,null,"expanded");
  }
}
for(const button of document.querySelectorAll("[data-range]"))button.addEventListener("click",()=>selectRange(button.dataset.range));
for(const tab of document.querySelectorAll(".chart-tabs [role=tab]"))tab.addEventListener("click",()=>selectExpanded(tab.dataset.chart));
document.querySelector(".chart-tabs").addEventListener("keydown",event=>{
  const names=charts.map(chart=>chart.name),index=names.indexOf(expandedChart.name);
  const next=event.key==="ArrowRight" ? (index+1)%3 : event.key==="ArrowLeft" ? (index+2)%3 : event.key==="Home" ? 0 : event.key==="End" ? 2 : null;
  if(next!==null){event.preventDefault();selectExpanded(names[next]);$("tab-"+names[next]).focus();}
});
function closeHistory(){
  $("history-dialog").close();expandedChart=null;document.body.classList.remove("modal-open");
}
$("history-close").addEventListener("click",closeHistory);
$("history-export").addEventListener("click",exportHistory);
$("history-dialog").addEventListener("cancel",event=>{event.preventDefault();closeHistory();});
$("history-dialog").addEventListener("close",()=>{if(!$("history-dialog").open){expandedChart=null;document.body.classList.remove("modal-open");}});
$("history-dialog").addEventListener("click",event=>{
  const box=event.currentTarget.getBoundingClientRect();
  if(event.target===event.currentTarget && (event.clientX<box.left || event.clientX>box.right || event.clientY<box.top || event.clientY>box.bottom))closeHistory();
});
$("expanded-chart").addEventListener("pointermove",event=>{if(expandedChart)drawChart(expandedChart,event.clientX-event.currentTarget.getBoundingClientRect().left,"expanded");});
$("expanded-chart").addEventListener("pointerleave",()=>{if(expandedChart)drawChart(expandedChart,null,"expanded");});
drawCharts();poll();

function curveMessage(text,error=false){$("curve-message").textContent=text;$("curve-message").classList.toggle("error",error);}
function readCurve(){
  const data={temperature_source:$("temperature_source").value,off_temp_c:Number($("off_temp_c").value),steps:[]};
  if($("off_temp_c").value==="")return null;
  if(!["max","gpu","cpu"].includes(data.temperature_source))return null;
  if(!Number.isFinite(data.off_temp_c) || data.off_temp_c<0 || data.off_temp_c>125)return null;
  let previousTemp=data.off_temp_c,previousPWM=20;
  const rows=[...$("curve-steps").children];
  if(rows.length<2 || rows.length>8)return null;
  for(const [index,row] of rows.entries()){
    const t=row.querySelector(".step-temperature").value,p=row.querySelector(".step-pwm").value;
    if(t==="" || p==="")return null;
    const temperature_c=Number(t),pwm_percent=Number(p);
    if(!Number.isFinite(temperature_c) || !(previousTemp<temperature_c && temperature_c<=125))return null;
    if(!Number.isFinite(pwm_percent) || !(previousPWM<=pwm_percent && pwm_percent<=100))return null;
    if(index===rows.length-1 ? pwm_percent!==100 : pwm_percent>=100)return null;
    data.steps.push({temperature_c,pwm_percent});previousTemp=temperature_c;previousPWM=pwm_percent;
  }
  return data;
}
function stepRows(steps){
  $("curve-steps").replaceChildren();
  steps.forEach((step,index)=>{
    const row=document.createElement("tr"),label=document.createElement("th");label.scope="row";
    label.textContent=index===0 ? "Restart at" : index===steps.length-1 ? "Full speed at" : "Step "+(index+1);
    row.append(label);
    for(const [key,cls,aria,min,max] of [["temperature_c","step-temperature","Step "+(index+1)+" temperature",0,125],["pwm_percent","step-pwm","Step "+(index+1)+" PWM",20,index===steps.length-1 ? 100 : 99]]){
      const cell=document.createElement("td"),input=document.createElement("input");input.type="number";input.className=cls;
      input.min=min;input.max=max;input.step=key==="temperature_c" ? "0.1" : "1";input.required=true;input.setAttribute("aria-label",aria);input.value=step[key];
      if(key==="pwm_percent" && index===steps.length-1){input.readOnly=true;input.tabIndex=-1;}
      cell.append(input);row.append(cell);
    }
    const action=document.createElement("td");
    if(index>0 && index<steps.length-1){
      const button=document.createElement("button");button.type="button";button.className="step-icon";button.textContent="\u2212";
      button.title="Remove step "+(index+1);button.setAttribute("aria-label",button.title);
      button.addEventListener("click",()=>{const remaining=[...$("curve-steps").children].filter(r=>r!==row).map(r=>({temperature_c:r.querySelector(".step-temperature").value,pwm_percent:r.querySelector(".step-pwm").value}));stepRows(remaining);curveEdited();});
      action.append(button);
    }
    row.append(action);$("curve-steps").append(row);
  });
}
function showCurve(data){
  if(!data || !validCurveSettings(data.settings))throw new Error("Invalid curve response");
  if(typeof data.automatic_control_active!=="boolean")throw new Error("Invalid automatic-control state");
  state.curve=data;state.curveLoaded=true;state.curveDirty=false;state.automatic=data.automatic_control_active;
  $("temperature_source").value=data.settings.temperature_source;$("off_temp_c").value=data.settings.off_temp_c;stepRows(data.settings.steps);
  $("curve-source").textContent=data.source==="file" ? "Loaded from fan_curve.json" : data.source==="session" ? "Session settings / not persisted" : "Draft defaults";
  curveMessage(state.automatic ? "Automatic control active; DGX temperatures are applying this curve" :
    "Automatic control paused; manual fan controls are available");
  drawCurve();controls();
}
function validCurveSettings(settings){
  if(!settings || !["max","gpu","cpu"].includes(settings.temperature_source) || !Number.isFinite(settings.off_temp_c) || settings.off_temp_c<0 || settings.off_temp_c>125)return false;
  if(!Array.isArray(settings.steps) || settings.steps.length<2 || settings.steps.length>8)return false;
  let temperature=settings.off_temp_c,pwm=20;
  return settings.steps.every((step,index)=>{
    if(!step || !Number.isFinite(step.temperature_c) || step.temperature_c<=temperature || step.temperature_c>125 || !Number.isFinite(step.pwm_percent) || step.pwm_percent<pwm || step.pwm_percent>100)return false;
    if(index===settings.steps.length-1 ? step.pwm_percent!==100 : step.pwm_percent>=100)return false;
    temperature=step.temperature_c;pwm=step.pwm_percent;return true;
  });
}
async function loadCurve(){
  $("curve-retry").disabled=true;
  try{showCurve(await request("/api/curve"));$("curve-retry").hidden=true;}
  catch(error){
    state.curveLoaded=false;state.nextCurveLoad=Date.now()+10000;$("curve-retry").hidden=false;
    const message=error.status===404 ? "Curve API missing (404). Restart the Pico to load the updated firmware, then retry." :
      error.message==="Invalid curve response" || error instanceof SyntaxError ? "Invalid curve response. Update the Pico firmware files and restart." :
      "Curve request failed. Check the connection and retry.";
    curveMessage(message,true);
  }finally{$("curve-retry").disabled=false;controls();}
}
$("curve-retry").addEventListener("click",loadCurve);
async function toggleCurve(){
  if(state.curveBusy || state.automatic===null)return;
  const activate=!state.automatic;
  state.curveBusy=true;controls();
  try{
    if(activate && state.curveDirty){
      const settings=readCurve();
      if(!settings)throw new Error("Fix the curve values before activation");
      showCurve(await request("/api/curve",settings));
    }
    showCurve(await request("/api/automatic",{active:activate}));
    if(activate){state.manual=null;message("Automatic temperature control activated");}
    else message("Automatic control paused; full speed used until a manual command");
  }catch(error){curveMessage(error.message+"; automatic state unconfirmed",true);}
  finally{state.curveBusy=false;controls();}
}
$("curve-toggle").addEventListener("click",toggleCurve);
async function applyCurve(event){
  event.preventDefault();const data=readCurve();
  if(!data || state.curveBusy)return;
  state.curveBusy=true;controls();
  try{showCurve(await request("/api/curve",data));}
  catch(error){curveMessage(error.message+"; curve not confirmed",true);}
  finally{state.curveBusy=false;controls();}
}
function drawCurve(){
  const canvas=$("curve-chart"),box=canvas.getBoundingClientRect(),ratio=devicePixelRatio || 1;
  canvas.width=Math.round(box.width*ratio);canvas.height=Math.round(box.height*ratio);
  const ctx=canvas.getContext("2d");ctx.scale(ratio,ratio);
  const c=readCurve(),max=c ? Math.max(100,Math.ceil(c.steps.at(-1).temperature_c/20)*20) : 100;
  const left=35,right=12,top=15,bottom=27,w=box.width-left-right,h=box.height-top-bottom;
  const x=value=>left+value/max*w,y=value=>top+(100-value)/100*h;
  ctx.font="10px system-ui";ctx.lineWidth=1;
  for(let i=0;i<=4;i++){
    const v=i*25;ctx.strokeStyle="#e2e7e4";ctx.beginPath();ctx.moveTo(left,y(v));ctx.lineTo(box.width-right,y(v));ctx.stroke();
    ctx.fillStyle="#728078";ctx.textAlign="right";ctx.fillText(v+"%",left-6,y(v)+3);
    ctx.textAlign=i===0 ? "left" : i===4 ? "right" : "center";ctx.fillText(fmt(i*max/4)+"\u00b0C",x(i*max/4),box.height-6);
  }
  if(!c)return;
  const first=c.steps[0];
  $("hysteresis").textContent="Hysteresis "+fmt(first.temperature_c-c.off_temp_c,1)+"\u00b0C";
  const warming=[[0,0]];let lastPWM=0;
  for(const step of c.steps){warming.push([step.temperature_c,lastPWM],[step.temperature_c,step.pwm_percent]);lastPWM=step.pwm_percent;}
  warming.push([max,100]);
  ctx.strokeStyle="#277a48";ctx.lineWidth=2;ctx.beginPath();
  warming.forEach(([t,duty],i)=>i ? ctx.lineTo(x(t),y(duty)) : ctx.moveTo(x(t),y(duty)));ctx.stroke();
  ctx.strokeStyle="#157c9b";ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(x(first.temperature_c),y(first.pwm_percent));ctx.lineTo(x(c.off_temp_c),y(first.pwm_percent));ctx.lineTo(x(c.off_temp_c),y(0));ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle="#277a48";
  for(const step of c.steps){ctx.beginPath();ctx.arc(x(step.temperature_c),y(step.pwm_percent),3.5,0,Math.PI*2);ctx.fill();}
}
function curveEdited(){
  state.curveDirty=true;
  curveMessage(readCurve() ? "Unsaved curve edits" : "Use increasing temperatures and nondecreasing PWM steps (20-99%), ending at 100%",!readCurve());
  drawCurve();controls();
}
$("curve-form").addEventListener("input",curveEdited);
$("curve-add").addEventListener("click",()=>{
  const c=readCurve();if(!c || c.steps.length>=8)return;
  const last=c.steps.at(-1),previous=c.steps.at(-2);
  const temperature_c=Math.round((previous.temperature_c+last.temperature_c)*5)/10;
  if(temperature_c<=previous.temperature_c || temperature_c>=last.temperature_c){curveMessage("Increase the temperature gap before full speed to add a step",true);return;}
  c.steps.splice(-1,0,{temperature_c,pwm_percent:Math.min(99,Math.round((previous.pwm_percent+last.pwm_percent)/2))});
  stepRows(c.steps);curveEdited();
});
$("curve-form").addEventListener("submit",applyCurve);
$("curve-discard").addEventListener("click",()=>showCurve(state.curve));
$("curve-download").addEventListener("click",()=>{
  const data=readCurve();if(!data)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)+"\n"],{type:"application/json"}));
  const link=document.createElement("a");link.href=url;link.download="fan_curve.json";link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
});
