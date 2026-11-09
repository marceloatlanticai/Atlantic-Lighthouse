/*
  THE LIGHTHOUSE MICROPHONE, for the live session screen.

  The session room's listener (components/listener) taken apart from its own
  screen so it can live INSIDE the session screen — start listening and decide
  a current on the same page, in one click each. The room's own listener is
  left exactly as it was.

  TWO ENGINES, chosen by the app (args.engine), unchanged from the listener:
    "chrome" — the browser's speech recognition. Free; Chrome sends the audio
               to Google; voices are not told apart (people are tapped).
    "aai"    — AssemblyAI streaming on its EU servers, voices told apart. The
               app mints a short-lived token; the key never reaches the page.
               16 kHz 16-bit PCM in 50 ms frames. Billed while the connection
               is open, so Stop always ends it properly.

  NEW HERE — GOOGLE MEET. The microphone hears only this room. On a call, the
  other side is in the Meet tab, so "Add the Meet tab" asks Chrome for that
  tab (getDisplayMedia, with "Also share tab audio" ticked) and MIXES its sound
  with the microphone before it goes to AssemblyAI, which tells every voice
  apart, in the room or on the call. Only with "aai": Chrome's free engine
  cannot be given a sound of our choosing, only the default microphone.

  NOTHING IS LOST, NOTHING IS SENT TWICE: every item is numbered and kept until
  the app acknowledges it (args.mic_ack) — the listener's own protocol.
*/
(function () {
  "use strict";
  function LhEngine(ui) {
    // ui: { flush(), onState(cls, label), onInterim(text), onMsg(text, fallback), onTab(on, why) }
    var args = { lang: "en-US", batch_words: 14, batch_seconds: 6, start_seq: 0, mic_ack: -1,
                 engine: "chrome", aai: null, aai_error: "" };
    var seq = -1, outbox = [], need = 0, listening = false, running = "", resumeAs = "";
    var sentWords = 0;

    function words(s) { return (String(s || "").match(/\S+/g) || []).length; }
    function pushItem(it) {
      seq += 1; it.seq = seq; it.lang = args.lang;
      outbox.push(it);
      if (outbox.length > 80) outbox = outbox.slice(-80);
      if (it.text) sentWords += words(it.text);
      ui.flush();
    }
    function requestToken() { need += 1; ui.flush(); }
    function setState(cls, label) { ui.onState(cls, label, listening); }
    function say(text, fallback) { ui.onMsg(text || "", !!fallback); }

    // ══ ENGINE 1 — Chrome's speech recognition ═════════════════════════════
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var rec = null, parts = [], lastFlush = Date.now(), segStart = {};
    var startedAt = 0, quickEnds = 0, restartTimer = null, netWarn = false;
    function scheduleRestart(delay) {
      if (restartTimer) return;
      restartTimer = setTimeout(function () { restartTimer = null; if (listening && running === "chrome") chromeBegin(); }, delay);
    }
    function disarm(r) { if (!r) return; r.onresult = r.onerror = r.onend = null; try { (r.abort || r.stop).call(r); } catch (e) {} }
    function chromeFlush(force) {
      if (!parts.length) return;
      var text = parts.map(function (p) { return p.x; }).join(" ").trim();
      var waited = (Date.now() - lastFlush) / 1000;
      if (!force && words(text) < args.batch_words && waited < args.batch_seconds) return;
      pushItem({ kind: "talk", text: text, parts: parts, t0: parts[0].t0, t1: parts[parts.length - 1].t1 });
      parts = []; lastFlush = Date.now();
    }
    function chromeBuild() {
      var r = new SR(); r.continuous = true; r.interimResults = true; r.lang = args.lang; segStart = {};
      r.onresult = function (ev) {
        if (r !== rec) return;
        if (netWarn) { say(""); netWarn = false; }
        var interim = "", now = Date.now();
        for (var i = ev.resultIndex; i < ev.results.length; i++) {
          var res = ev.results[i];
          if (!segStart[i]) segStart[i] = now;
          if (res.isFinal) { var x = String(res[0].transcript || "").trim(); if (x) parts.push({ x: x, t0: segStart[i], t1: now }); delete segStart[i]; }
          else interim += res[0].transcript;
        }
        ui.onInterim(interim);
        chromeFlush(false);
      };
      r.onerror = function (ev) {
        if (r !== rec) return;
        var code = ev.error || "";
        if (code === "not-allowed" || code === "service-not-allowed") { say("Microphone blocked. Allow it for this site in the browser bar, then press Listen again."); stopAll(); return; }
        if (code === "audio-capture") { say("No microphone found on this computer."); stopAll(); return; }
        if (code === "network") { say("Speech service unreachable — retrying."); netWarn = true; }
      };
      r.onend = function () {
        if (r !== rec) return;
        if (!listening || running !== "chrome") { chromeFlush(true); ui.onInterim(""); return; }
        if (restartTimer) return;
        var lived = Date.now() - startedAt;
        quickEnds = lived < 1500 ? quickEnds + 1 : 0;
        if (quickEnds >= 5) { say("Listening keeps stopping. Check the microphone, then press Listen again."); chromeFlush(true); stopAll(); return; }
        scheduleRestart(quickEnds ? 600 * quickEnds : 150);
      };
      return r;
    }
    function chromeBegin() { disarm(rec); rec = chromeBuild(); startedAt = Date.now(); try { rec.start(); } catch (e) {} }
    function chromeStart() {
      if (!SR) { say("This browser has no speech recognition. Use Chrome or Edge."); stopAll(); return; }
      running = "chrome"; quickEnds = 0; setState("on", "Listening"); chromeBegin();
    }
    function chromeStop() {
      if (restartTimer) { clearTimeout(restartTimer); restartTimer = null; }
      try { if (rec) rec.stop(); } catch (e) {}
      chromeFlush(true); ui.onInterim("");
    }

    // ══ ENGINE 2 — AssemblyAI streaming, voices told apart ═════════════════
    var A = { stream: null, tab: null, ctx: null, node: null, mix: null, src: null, tabSrc: null, conn: null,
              queue: [], waitingToken: false, tries: 0, retryT: 0, rotateT: 0, model: "" };
    var MAX_QUEUE = 40;
    var WORKLET = [
      "class LhPcm extends AudioWorkletProcessor {",
      "  constructor() { super(); this.r = sampleRate / 16000; this.t = 0; this.last = 0; this.y = 0;",
      "    this.a = this.r > 1.01 ? 1 - Math.exp(-2 * Math.PI * 7000 / sampleRate) : 1;",
      "    this.out = new Int16Array(800); this.n = 0; }",
      "  process(inputs) {",
      "    var x = inputs[0] && inputs[0][0]; if (!x) return true;",
      "    var a = this.a, f = new Float32Array(x.length), y = this.y;",
      "    for (var k = 0; k < x.length; k++) { y += a * (x[k] - y); f[k] = y; }",
      "    this.y = y;",
      "    var t = this.t;",
      "    while (t < f.length - 1) {",
      "      var i = Math.floor(t), fr = t - i, p = i < 0 ? this.last : f[i], q = f[i + 1];",
      "      var v = p + (q - p) * fr; v = v < -1 ? -1 : v > 1 ? 1 : v;",
      "      this.out[this.n++] = v < 0 ? v * 32768 : v * 32767;",
      "      if (this.n === 800) { this.port.postMessage(this.out.buffer.slice(0)); this.n = 0; }",
      "      t += this.r;",
      "    }",
      "    this.last = f[f.length - 1]; this.t = t - f.length;",
      "    return true;",
      "  }",
      "}",
      "registerProcessor('lh-pcm', LhPcm);"
    ].join("\n");
    function tokenOk() { return !!(args.aai && args.aai.token && (+args.aai.exp || 0) * 1000 - Date.now() > 15000); }
    function aaiStart() {
      running = "aai"; A.tries = 0;
      setState("wait", "Starting the microphone…");
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { say("This browser cannot open the microphone here."); stopAll(); return; }
      navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
        .then(function (stream) {
          if (!listening || running !== "aai") { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
          A.stream = stream;
          return audioUp(stream).then(function () { aaiConnect(); });
        })
        .catch(function (e) {
          var n = (e && e.name) || "";
          say(n === "NotAllowedError" ? "Microphone blocked. Allow it for this site in the browser bar, then press Listen again."
            : n === "NotFoundError" ? "No microphone found on this computer." : "The microphone could not start (" + (e && e.message || n) + ").");
          stopAll();
        });
    }
    function audioUp(stream) {
      var AC = window.AudioContext || window.webkitAudioContext, ctx;
      try { ctx = new AC({ sampleRate: 16000 }); } catch (e) { ctx = new AC(); }
      A.ctx = ctx;
      if (!ctx.audioWorklet) return Promise.reject(new Error("no AudioWorklet in this browser"));
      var url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      return ctx.audioWorklet.addModule(url).then(function () {
        URL.revokeObjectURL(url);
        // THE MIXER: the microphone and, when added, the Meet tab — one voice
        // stream, folded to mono, for the service to tell the voices apart.
        A.mix = ctx.createGain();
        A.mix.channelCount = 1; A.mix.channelCountMode = "explicit"; A.mix.channelInterpretation = "speakers";
        A.src = ctx.createMediaStreamSource(stream);
        A.src.connect(A.mix);
        A.node = new AudioWorkletNode(ctx, "lh-pcm");
        A.node.port.onmessage = function (ev) { audioFrame(ev.data); };
        A.mix.connect(A.node);
        var mute = ctx.createGain(); mute.gain.value = 0; A.node.connect(mute); mute.connect(ctx.destination);
        if (A.tab) tabConnect();
        if (ctx.state === "suspended") return ctx.resume();
      });
    }
    function audioDown() {
      try { if (A.src) A.src.disconnect(); } catch (e) {}
      try { if (A.tabSrc) A.tabSrc.disconnect(); } catch (e) {}
      try { if (A.node) { A.node.port.onmessage = null; A.node.disconnect(); } } catch (e) {}
      try { if (A.ctx) A.ctx.close(); } catch (e) {}
      try { if (A.stream) A.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
      A.src = A.tabSrc = A.node = A.ctx = A.stream = A.mix = null; A.queue = [];
    }
    function audioFrame(buf) {
      var c = A.conn;
      if (c && c.ws && c.ws.readyState === 1 && c.begun) {
        while (A.queue.length) { c.ws.send(A.queue.shift()); c.sent += 1; }
        c.ws.send(buf); c.sent += 1;
      } else { A.queue.push(buf); if (A.queue.length > MAX_QUEUE) A.queue.shift(); }
    }
    function aaiConnect() {
      if (!listening || running !== "aai") return;
      if (!tokenOk()) { A.waitingToken = true; setState("wait", "Connecting…"); requestToken(); return; }
      A.waitingToken = false;
      var a = args.aai;
      var ep = Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
      var q = { sample_rate: 16000, speech_model: a.model, speaker_labels: "true", format_turns: "true", token: a.token };
      if (a.revise_ms) q.speaker_labels_revision_interval_ms = a.revise_ms;
      var url = a.url + "?" + Object.keys(q).map(function (k) { return k + "=" + encodeURIComponent(q[k]); }).join("&");
      var c = { ws: null, ep: ep, sent: 0, begun: false, done: {}, pending: null, pendT: 0, model: a.model, closing: false };
      try { c.ws = new WebSocket(url); } catch (e) { connLost(c, "could not open the connection"); return; }
      c.ws.binaryType = "arraybuffer";
      A.conn = c; A.model = a.model;
      setState("wait", "Connecting…");
      c.ws.onmessage = function (ev) { onMessage(c, ev); };
      c.ws.onclose = function (ev) { onClose(c, ev); };
      c.ws.onerror = function () {};
    }
    function onMessage(c, ev) {
      var m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.type === "Begin") {
        c.begun = true; A.tries = 0;
        if (c === A.conn) { say(""); setState("on", A.tab ? "Listening · this room + the Meet tab" : "Listening · voices told apart"); }
        var maxS = (args.aai && +args.aai.max_s) || 10800;
        var ends = m.expires_at ? +m.expires_at * 1000 : Date.now() + maxS * 1000;
        clearTimeout(A.rotateT);
        A.rotateT = setTimeout(function () { if (c === A.conn && listening) rotate(); }, Math.max(60000, Math.min(ends, Date.now() + maxS * 1000) - Date.now() - 90000));
      } else if (m.type === "Turn") onTurn(c, m);
      else if (m.type === "SpeakerRevision") {
        var revs = (m.revisions || []).filter(function (r) { return r && typeof r.turn_order === "number"; })
          .map(function (r) { return [r.turn_order, String(r.speaker_label || "")]; });
        if (revs.length) pushItem({ kind: "rev", ep: c.ep, revs: revs });
      } else if (m.type === "Error") c.error = (m.error_code ? m.error_code + " · " : "") + (m.error || "error");
      else if (m.type === "Termination") c.terminated = true;
    }
    function onTurn(c, m) {
      if (c.pending && c.pending.turn !== m.turn_order) commit(c, c.pending);
      if (!m.end_of_turn) { if (c === A.conn) ui.onInterim(m.transcript || ""); return; }
      var w = m.words || [], now = Date.now(), sentMs = c.sent * 50;
      var back = function (ms) { return Math.round(now - Math.max(0, sentMs - (+ms || 0))); };
      var it = { kind: "turn", ep: c.ep, turn: m.turn_order, spk: String(m.speaker_label || ""), text: String(m.transcript || "").trim(),
                 t0: w.length ? back(w[0].start) : now, t1: w.length ? back(w[w.length - 1].end) : now };
      if (m.turn_is_formatted) commit(c, it);
      else { c.pending = it; clearTimeout(c.pendT); c.pendT = setTimeout(function () { if (c.pending === it) commit(c, it); }, 2500); }
      if (c === A.conn) ui.onInterim("");
    }
    function commit(c, it) {
      if (c.pending === it || (c.pending && c.pending.turn === it.turn)) { c.pending = null; clearTimeout(c.pendT); }
      if (c.done[it.turn] || !it.text) return;
      c.done[it.turn] = 1; pushItem(it);
    }
    function onClose(c, ev) {
      if (c.pending) commit(c, c.pending);
      if (c !== A.conn) return;
      A.conn = null;
      if (!listening || running !== "aai" || c.closing) return;
      connLost(c, c.error || (ev && ev.reason) || ("closed, code " + (ev && ev.code)));
    }
    function connLost(c, why) {
      if (!c.begun) {
        if (A.tries < 1) { A.tries += 1; args.aai = null; aaiConnect(); return; }
        say("AssemblyAI did not accept the connection — " + why + ".", true); stopAll(); return;
      }
      A.tries += 1;
      if (A.tries > 6) { say("Lost the connection to AssemblyAI — " + why + ". Press Listen to try again.", true); stopAll(); return; }
      setState("wait", "Reconnecting…");
      clearTimeout(A.retryT); A.retryT = setTimeout(aaiConnect, Math.min(8000, 700 * A.tries));
    }
    function endConn(c, hard) {
      if (!c || !c.ws) return;
      c.closing = true;
      try { if (c.ws.readyState === 1) c.ws.send(JSON.stringify({ type: "Terminate" })); } catch (e) {}
      var ws = c.ws;
      if (hard) { try { ws.close(1000); } catch (e) {} return; }
      setTimeout(function () { try { ws.close(1000); } catch (e) {} }, 5000);
    }
    function rotate() { var old = A.conn; A.conn = null; endConn(old, false); aaiConnect(); }
    function aaiStop() {
      clearTimeout(A.retryT); clearTimeout(A.rotateT); A.waitingToken = false;
      var c = A.conn; A.conn = null; audioDown(); endConn(c, false); ui.onInterim("");
    }

    // ── The Meet tab ─────────────────────────────────────────────────────────
    function tabConnect() {
      if (!A.ctx || !A.mix || !A.tab) return;
      try { if (A.tabSrc) A.tabSrc.disconnect(); } catch (e) {}
      A.tabSrc = A.ctx.createMediaStreamSource(A.tab);
      A.tabSrc.connect(A.mix);
    }
    function addTab() {
      if (args.engine !== "aai") { ui.onTab(false, "Google Meet needs the voices mode (AssemblyAI) — the free mode only hears this computer's microphone."); return; }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) { ui.onTab(false, "This browser cannot share a tab. Use Chrome or Edge."); return; }
      navigator.mediaDevices.getDisplayMedia({ video: true, audio: { suppressLocalAudioPlayback: false },
                                               preferCurrentTab: false, selfBrowserSurface: "exclude",
                                               surfaceSwitching: "include", systemAudio: "include" })
        .then(function (s) {
          var au = s.getAudioTracks();
          s.getVideoTracks().forEach(function (t) { t.stop(); });     // only the sound is needed
          if (!au.length) {
            s.getTracks().forEach(function (t) { t.stop(); });
            ui.onTab(false, "No sound came with the tab. Add it again, choose the Meet tab and tick “Also share tab audio”.");
            return;
          }
          if (A.tab) A.tab.getTracks().forEach(function (t) { t.stop(); });
          A.tab = new MediaStream(au);
          au[0].addEventListener("ended", function () { removeTab("The Meet tab stopped sharing."); });
          tabConnect();
          ui.onTab(true, "");
          if (A.conn && A.conn.begun) setState("on", "Listening · this room + the Meet tab");
        })
        .catch(function (e) {
          var n = (e && e.name) || "";
          ui.onTab(false, n === "NotAllowedError" ? "Tab sharing was cancelled or is not allowed on this page. Open the session screen on the app's own address (not inside another site) and try again."
                                                  : "The tab could not be shared (" + (e && e.message || n) + ").");
        });
    }
    function removeTab(why) {
      try { if (A.tabSrc) A.tabSrc.disconnect(); } catch (e) {}
      try { if (A.tab) A.tab.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
      A.tab = null; A.tabSrc = null;
      ui.onTab(false, why || "");
      if (A.conn && A.conn.begun) setState("on", "Listening · voices told apart");
    }

    // ── Start / stop / switch ────────────────────────────────────────────────
    function startEngine() {
      say("");
      if (args.engine === "aai") {
        if (!args.aai && args.aai_error) { say(args.aai_error, true); stopAll(); return; }
        aaiStart();
      } else chromeStart();
    }
    function stopEngine() { if (running === "chrome") chromeStop(); if (running === "aai") aaiStop(); running = ""; }
    function stopAll() { listening = false; stopEngine(); setState("", "Not listening"); }
    function start() { if (listening) return; listening = true; startEngine(); }
    window.addEventListener("pagehide", function () { if (A.conn) endConn(A.conn, true); });
    setInterval(function () { if (running === "chrome" && parts.length) chromeFlush(false); }, 2000);

    function setArgs(a) {
      a = a || {};
      ["lang", "batch_words", "batch_seconds", "engine", "aai_error"].forEach(function (k) { if (a[k] !== undefined && a[k] !== null) args[k] = a[k]; });
      if (a.aai !== undefined) args.aai = a.aai;
      // never reuse a number the app has already taken (a reload starts from scratch)
      if (typeof a.start_seq === "number" && seq < a.start_seq - 1) seq = a.start_seq - 1;
      if (typeof a.mic_ack === "number") outbox = outbox.filter(function (it) { return it.seq > a.mic_ack; });
      if (resumeAs && args.engine === resumeAs && !listening) { resumeAs = ""; listening = true; startEngine(); }
      else if (listening) {
        if (args.engine !== running && running) { stopEngine(); startEngine(); }
        else if (running === "chrome" && rec && rec.lang !== args.lang) { try { rec.stop(); } catch (er) {} }
        else if (running === "aai") {
          if (A.waitingToken && tokenOk()) aaiConnect();
          else if (!args.aai && args.aai_error && !A.conn) { say(args.aai_error, true); stopAll(); }
          else if (A.conn && args.aai && args.aai.model && args.aai.model !== A.model && A.conn.begun) rotate();
        }
      }
      if (args.engine !== "aai" && A.tab) removeTab("");
    }
    return {
      setArgs: setArgs, start: start, stop: stopAll, addTab: addTab, removeTab: removeTab,
      useFree: function () { resumeAs = "chrome"; },
      listening: function () { return listening; }, running: function () { return running; },
      tabOn: function () { return !!A.tab; },
      outbox: function () { return outbox; }, need: function () { return need; },
      words: function () { return sentWords; },
      state: function () { return { listening: listening, running: running, seq: seq, outbox: outbox.length, need: need,
                                    conn: A.conn ? { ep: A.conn.ep, begun: A.conn.begun } : null, queue: A.queue.length, tab: !!A.tab }; }
    };
  }
  window.LhEngine = LhEngine;
})();
