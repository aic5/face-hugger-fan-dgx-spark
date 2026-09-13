"use strict";
window.addEventListener("load", () => {
  const script = document.createElement("script");
  script.src = "/dashboard.js?v=7";
  script.onerror = () => {
    const badge = document.getElementById("connection");
    if (badge) {
      badge.textContent = "Page load interrupted";
      badge.className = "badge error";
    }
  };
  document.body.append(script);
}, {once:true});
