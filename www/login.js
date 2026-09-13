"use strict";
const form=document.getElementById("login-form");
const button=document.getElementById("login-submit");
const message=document.getElementById("login-message");

async function session(){
  try{
    const response=await fetch("/api/session",{cache:"no-store"});
    const data=await response.json();
    if(data.authenticated)location.replace("/");
  }catch(error){message.textContent="Controller unavailable";message.className="error";}
}

form.addEventListener("submit",async event=>{
  event.preventDefault();button.disabled=true;message.textContent="Signing in…";message.className="";
  try{
    const response=await fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({username:form.username.value,password:form.password.value}),cache:"no-store"});
    if(!response.ok)throw new Error(response.status===401 ? "Invalid username or password" : "Sign-in failed ("+response.status+")");
    location.replace("/");
  }catch(error){message.textContent=error.message;message.className="error";button.disabled=false;form.password.select();}
});

session();
