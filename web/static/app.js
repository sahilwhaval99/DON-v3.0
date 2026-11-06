/* DON v3.0 dashboard front-end */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  let speakFn = null;  // set up in the Voice section; called when DON replies

  // Clock
  function tick(){
    const n = new Date();
    $("#clock").textContent = n.toLocaleTimeString([], {hour12:false});
    $("#date").textContent = n.toLocaleDateString([], {weekday:"long", month:"short", day:"numeric"});
  }
  setInterval(tick, 1000); tick();

  // Conversation
  const convo = $("#convo");
  function add(role, text){
    const w = document.createElement("div");
    w.className = "msg " + role;
    const b = document.createElement("div");
    b.className = "b";
    b.textContent = text;
    w.appendChild(b);
    convo.appendChild(w);
    convo.scrollTop = convo.scrollHeight;
    return w;
  }
  function logActivity(t){
    const log = $("#log");
    const li = document.createElement("li");
    li.textContent = t;
    log.prepend(li);
    while (log.children.length > 30) log.lastChild.remove();
  }

  // Send message
  const form = $("#form"), input = $("#text"), sendBtn = $("#send");
  async function send(text){
    text = (text || "").trim();
    if (!text) return;
    add("user", text);
    input.value = "";
    sendBtn.disabled = true;

    // Create an empty DON bubble we fill as chunks stream in.
    const bubbleWrap = add("don", "");
    const bubble = bubbleWrap.querySelector(".b");
    bubble.textContent = "…";
    let full = "";
    try {
      // Try streaming first
      const res = await fetch("/api/chat_stream", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({text})
      });
      if (!res.ok || !res.body) throw new Error("stream-fail");
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let first = true;
      while (true){
        const {done, value} = await reader.read();
        if (done) break;
        const chunk = dec.decode(value, {stream:true});
        if (first){ bubble.textContent = ""; first = false; }
        full += chunk;
        bubble.textContent = full;
        convo.scrollTop = convo.scrollHeight;
      }
      if (!full) throw new Error("empty-stream");
      if (speakFn && full) speakFn(full);
      logActivity("You: " + text.slice(0, 40));
      refreshReminders();
    } catch(streamErr){
      // Fallback: use the non-streaming endpoint
      try {
        const res2 = await fetch("/api/chat", {
          method:"POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({text})
        });
        const data = await res2.json();
        full = data.reply || "…";
        bubble.textContent = full;
        if (speakFn && full) speakFn(full);
        logActivity("You: " + text.slice(0, 40));
        refreshReminders();
      } catch(e2){
        bubble.textContent = "Connection error: " + e2.message + " (is the server still running?)";
      }
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });

  // Example prompts
  $("#examples").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-q]");
    if (li) send(li.dataset.q);
  });

  // Status
  async function refreshStatus(){
    try{
      const s = await (await fetch("/api/status")).json();
      $("#fmodel").textContent = s.model;
      $("#fup").textContent = s.uptime;
      const dot = $("#dot"), stat = $("#stat"), fb = $("#fbrain");
      if (s.brain_ready){
        dot.className = "dot on"; stat.textContent = "ONLINE";
        fb.textContent = "Brain: online"; fb.className = "ok";
      } else {
        dot.className = "dot off"; stat.textContent = "NO API KEY";
        fb.textContent = "Brain: offline (add GEMINI_API_KEY to .env)"; fb.className = "warn";
      }
    }catch(_){}
  }
  refreshStatus(); setInterval(refreshStatus, 5000);

  async function refreshReminders(){
    try{
      const data = await (await fetch("/api/reminders")).json();
      const ul = $("#reminders");
      const items = data.reminders || [];
      if (!items.length){ ul.innerHTML = '<li class="empty">None yet.</li>'; return; }
      ul.innerHTML = items.map(r =>
        `<li>${(r.message||"").replace(/</g,"&lt;")} <span style="color:#7c8aa5">@ ${r.due}</span></li>`
      ).join("");
    }catch(_){}
  }
  refreshReminders(); setInterval(refreshReminders, 10000);

  // WebSocket live stats
  function connectWS(){
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (ev) => {
      let m; try{ m = JSON.parse(ev.data); }catch{ return; }
      setGauge("#cpu","#cpuv", m.cpu);
      setGauge("#mem","#memv", m.memory);
      if (m.uptime) $("#fup").textContent = m.uptime;
    };
    ws.onclose = () => setTimeout(connectWS, 2000);
    ws.onerror = () => { try{ ws.close(); }catch(_){} };
  }
  function setGauge(bar, val, pct){
    pct = Math.max(0, Math.min(100, Number(pct)||0));
    $(bar).style.width = pct + "%";
    $(val).textContent = pct.toFixed(0) + "%";
  }
  connectWS();

  // Animated grid background
  const bg = $("#bg"), g = bg.getContext("2d");
  function resize(){ bg.width = innerWidth; bg.height = innerHeight; }
  addEventListener("resize", resize); resize();
  let off = 0;
  (function draw(){
    g.clearRect(0,0,bg.width,bg.height);
    const sp = 44; off = (off + 0.25) % sp;
    for (let x=-sp+off; x<bg.width; x+=sp){ g.strokeStyle="rgba(2,151,222,.06)"; g.beginPath(); g.moveTo(x,0); g.lineTo(x,bg.height); g.stroke(); }
    for (let y=-sp+off; y<bg.height; y+=sp){ g.strokeStyle="rgba(252,115,77,.05)"; g.beginPath(); g.moveTo(0,y); g.lineTo(bg.width,y); g.stroke(); }
    requestAnimationFrame(draw);
  })();

  // ---------------- Voice ----------------
  // Speech OUTPUT (DON speaks replies) — on by default.
  let speakOn = true;
  const speakToggle = $("#speakToggle");
  function speak(text){
    if (!speakOn || !("speechSynthesis" in window)) return;
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.05; u.pitch = 1.0;
      // Prefer a British male-ish voice if available (JARVIS vibe).
      const voices = window.speechSynthesis.getVoices();
      const pref = voices.find(v => /en-GB/i.test(v.lang)) ||
                   voices.find(v => /en/i.test(v.lang));
      if (pref) u.voice = pref;
      window.speechSynthesis.speak(u);
    } catch(_){}
  }
  speakToggle.addEventListener("click", () => {
    speakOn = !speakOn;
    speakToggle.classList.toggle("off", !speakOn);
    speakToggle.textContent = speakOn ? "🔊" : "🔇";
    if (!speakOn) window.speechSynthesis && window.speechSynthesis.cancel();
  });
  speakFn = speak;  // wire speech output into the send() flow

  // Speech INPUT (mic → text) using the browser's SpeechRecognition.
  const mic = $("#mic");
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recog = null, listening = false;
  if (SR){
    recog = new SR();
    recog.lang = "en-US";
    recog.interimResults = false;
    recog.maxAlternatives = 1;
    recog.onresult = (e) => {
      const said = e.results[0][0].transcript;
      input.value = said;
      send(said);                 // auto-send what you spoke
    };
    recog.onend = () => { listening = false; mic.classList.remove("rec"); };
    recog.onerror = () => { listening = false; mic.classList.remove("rec"); };
    mic.addEventListener("click", () => {
      if (listening){ recog.stop(); return; }
      try { recog.start(); listening = true; mic.classList.add("rec"); logActivity("🎙 Listening…"); }
      catch(_){}
    });
  } else {
    mic.disabled = true;
    mic.title = "Voice input not supported in this browser (try Chrome/Edge)";
    mic.style.opacity = .4;
  }

  input.focus();
})();
