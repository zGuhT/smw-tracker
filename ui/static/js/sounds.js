/* ── SMW Tracker — Sound Alert Engine ── */

const SFX = (() => {
  let ctx = null;
  let settings = {
    gold: true, ahead: true, behind: true,
    pb: true, complete: true, start: false,
    volume: 50,
  };

  function getCtx() {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  function vol() { return settings.volume / 100; }

  function playTone(freq, duration, type = "sine", delay = 0) {
    const c = getCtx();
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(vol() * 0.3, c.currentTime + delay);
    gain.gain.exponentialRampToValueAtTime(0.001, c.currentTime + delay + duration);
    osc.connect(gain);
    gain.connect(c.destination);
    osc.start(c.currentTime + delay);
    osc.stop(c.currentTime + delay + duration);
  }

  function playChord(notes) {
    // notes: [{freq, duration, type, delay}]
    for (const n of notes) {
      playTone(n.freq, n.duration || 0.3, n.type || "sine", n.delay || 0);
    }
  }

  // ── Alert Sounds ──

  const sounds = {
    gold() {
      // Bright ascending arpeggio
      playChord([
        { freq: 880, duration: 0.15, type: "triangle", delay: 0 },
        { freq: 1108, duration: 0.15, type: "triangle", delay: 0.1 },
        { freq: 1318, duration: 0.25, type: "triangle", delay: 0.2 },
        { freq: 1760, duration: 0.4, type: "sine", delay: 0.3 },
      ]);
    },

    ahead() {
      // Quick rising double-tone
      playChord([
        { freq: 660, duration: 0.12, type: "sine", delay: 0 },
        { freq: 880, duration: 0.2, type: "sine", delay: 0.1 },
      ]);
    },

    behind() {
      // Quick descending tone
      playChord([
        { freq: 440, duration: 0.12, type: "square", delay: 0 },
        { freq: 330, duration: 0.2, type: "square", delay: 0.1 },
      ]);
    },

    pb() {
      // Celebration fanfare
      playChord([
        { freq: 523, duration: 0.15, type: "triangle", delay: 0 },
        { freq: 659, duration: 0.15, type: "triangle", delay: 0.12 },
        { freq: 784, duration: 0.15, type: "triangle", delay: 0.24 },
        { freq: 1047, duration: 0.5, type: "sine", delay: 0.36 },
        { freq: 784, duration: 0.5, type: "sine", delay: 0.36 },
        { freq: 1318, duration: 0.6, type: "sine", delay: 0.56 },
      ]);
    },

    complete() {
      // Completion jingle
      playChord([
        { freq: 523, duration: 0.2, type: "triangle", delay: 0 },
        { freq: 659, duration: 0.2, type: "triangle", delay: 0.15 },
        { freq: 784, duration: 0.3, type: "triangle", delay: 0.3 },
      ]);
    },

    start() {
      // Short beep
      playChord([
        { freq: 880, duration: 0.1, type: "sine", delay: 0 },
      ]);
    },
  };

  // ── Public API ──

  function play(type) {
    if (!settings[type]) return;
    if (sounds[type]) sounds[type]();
  }

  function loadSettings() {
    try {
      const saved = localStorage.getItem("sfc_sound_settings");
      if (saved) {
        const parsed = JSON.parse(saved);
        Object.assign(settings, parsed);
      }
    } catch {}
    applyToUI();
  }

  function saveSettings() {
    readFromUI();
    try {
      localStorage.setItem("sfc_sound_settings", JSON.stringify(settings));
    } catch {}
  }

  function readFromUI() {
    const ids = ["gold", "ahead", "behind", "pb", "complete", "start"];
    for (const id of ids) {
      const el = document.getElementById(`snd-${id}`);
      if (el) settings[id] = el.checked;
    }
    const vol = document.getElementById("snd-volume");
    if (vol) settings.volume = parseInt(vol.value) || 50;
  }

  function applyToUI() {
    const ids = ["gold", "ahead", "behind", "pb", "complete", "start"];
    for (const id of ids) {
      const el = document.getElementById(`snd-${id}`);
      if (el) el.checked = !!settings[id];
    }
    const vol = document.getElementById("snd-volume");
    if (vol) vol.value = settings.volume;
  }

  function isEnabled(type) { return !!settings[type]; }

  return { play, loadSettings, saveSettings, isEnabled, sounds };
})();
