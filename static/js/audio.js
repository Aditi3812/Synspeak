// Web Audio API sound synthesis for Synspeak study notifications & One-Flag Challenge
class AudioManager {
    constructor() {
        this.ctx = null;
        this.enabled = true;
        this.lastPlayedSound = null;
        this.lastPlayTime = 0;
    }

    _initContext() {
        if (!this.ctx) {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) {
                this.ctx = new AudioContext();
            }
        }
        if (this.ctx && this.ctx.state === 'suspended') {
            this.ctx.resume().catch(() => {});
        }
    }

    _canPlay(soundKey, throttleMs = 2000) {
        if (!this.enabled) return false;
        const now = Date.now();
        if (this.lastPlayedSound === soundKey && (now - this.lastPlayTime) < throttleMs) {
            return false;
        }
        this.lastPlayedSound = soundKey;
        this.lastPlayTime = now;
        return true;
    }

    playGentleChime() {
        if (!this._canPlay('gentle_chime', 3000)) return;
        try {
            this._initContext();
            if (!this.ctx) return;
            const now = this.ctx.currentTime;
            
            // Dual sine wave chime (E5 and B5)
            const osc1 = this.ctx.createOscillator();
            const osc2 = this.ctx.createOscillator();
            const gain = this.ctx.createGain();

            osc1.type = 'sine';
            osc1.frequency.setValueAtTime(659.25, now); // E5
            osc1.frequency.exponentialRampToValueAtTime(880, now + 0.3);

            osc2.type = 'sine';
            osc2.frequency.setValueAtTime(987.77, now); // B5

            gain.gain.setValueAtTime(0.08, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);

            osc1.connect(gain);
            osc2.connect(gain);
            gain.connect(this.ctx.destination);

            osc1.start(now);
            osc2.start(now);
            osc1.stop(now + 0.45);
            osc2.stop(now + 0.45);
        } catch (e) {
            console.warn("Audio play error:", e);
        }
    }

    playMinorWarning() {
        if (!this._canPlay('minor_warning', 2500)) return;
        try {
            this._initContext();
            if (!this.ctx) return;
            const now = this.ctx.currentTime;
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();

            osc.type = 'sine';
            osc.frequency.setValueAtTime(440, now); // A4
            osc.frequency.setValueAtTime(554.37, now + 0.15); // C#5

            gain.gain.setValueAtTime(0.1, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);

            osc.connect(gain);
            gain.connect(this.ctx.destination);

            osc.start(now);
            osc.stop(now + 0.45);
        } catch (e) {
            console.warn("Minor warning error:", e);
        }
    }

    playCriticalWarning() {
        if (!this._canPlay('critical_warning', 2000)) return;
        try {
            this._initContext();
            if (!this.ctx) return;
            const now = this.ctx.currentTime;
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();

            osc.type = 'triangle';
            osc.frequency.setValueAtTime(400, now);
            osc.frequency.setValueAtTime(600, now + 0.12);
            osc.frequency.setValueAtTime(400, now + 0.24);
            osc.frequency.setValueAtTime(600, now + 0.36);

            gain.gain.setValueAtTime(0.15, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.55);

            osc.connect(gain);
            gain.connect(this.ctx.destination);

            osc.start(now);
            osc.stop(now + 0.6);
        } catch (e) {
            console.warn("Critical warning error:", e);
        }
    }

    playPunishmentActivated() {
        if (!this._canPlay('punishment_activated', 3000)) return;
        try {
            this._initContext();
            if (!this.ctx) return;
            const now = this.ctx.currentTime;
            
            // Urgent 4-tone alert (G4 -> C5 -> G4 -> C5)
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();

            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(392.00, now);
            osc.frequency.setValueAtTime(523.25, now + 0.15);
            osc.frequency.setValueAtTime(392.00, now + 0.3);
            osc.frequency.setValueAtTime(523.25, now + 0.45);

            gain.gain.setValueAtTime(0.16, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.7);

            osc.connect(gain);
            gain.connect(this.ctx.destination);

            osc.start(now);
            osc.stop(now + 0.75);
        } catch (e) {
            console.warn("Punishment alert error:", e);
        }
    }

    playMajorAlert() {
        this.playPunishmentActivated();
    }

    playPunishmentReset() {
        if (!this._canPlay('punishment_reset', 2000)) return;
        try {
            this._initContext();
            if (!this.ctx) return;
            const now = this.ctx.currentTime;
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();

            // Downward penalty buzzer
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(520, now);
            osc.frequency.exponentialRampToValueAtTime(220, now + 0.35);

            gain.gain.setValueAtTime(0.15, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);

            osc.connect(gain);
            gain.connect(this.ctx.destination);

            osc.start(now);
            osc.stop(now + 0.42);
        } catch (e) {
            console.warn("Punishment reset error:", e);
        }
    }

    playPunishmentCompleted() {
        this.playRecoverySuccess();
    }

    playRecoverySuccess() {
        if (!this._canPlay('recovery_success', 3000)) return;
        try {
            this._initContext();
            if (!this.ctx) return;
            const now = this.ctx.currentTime;
            
            // Fanfare: C5 -> E5 -> G5 -> C6
            [523.25, 659.25, 783.99, 1046.50].forEach((freq, idx) => {
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                const start = now + (idx * 0.12);

                osc.type = 'sine';
                osc.frequency.setValueAtTime(freq, start);

                gain.gain.setValueAtTime(0.12, start);
                gain.gain.exponentialRampToValueAtTime(0.001, start + 0.45);

                osc.connect(gain);
                gain.connect(this.ctx.destination);

                osc.start(start);
                osc.stop(start + 0.5);
            });
        } catch (e) {
            console.warn("Recovery success audio error:", e);
        }
    }

    playFocusReward() {
        if (!this._canPlay('focus_reward', 3000)) return;
        try {
            this._initContext();
            if (!this.ctx) return;
            const now = this.ctx.currentTime;
            
            // Bright harmonic sparkle
            [659.25, 830.61, 987.77].forEach((freq, idx) => {
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                const start = now + (idx * 0.08);

                osc.type = 'triangle';
                osc.frequency.setValueAtTime(freq, start);

                gain.gain.setValueAtTime(0.1, start);
                gain.gain.exponentialRampToValueAtTime(0.001, start + 0.35);

                osc.connect(gain);
                gain.connect(this.ctx.destination);

                osc.start(start);
                osc.stop(start + 0.4);
            });
        } catch (e) {
            console.warn("Focus reward error:", e);
        }
    }

    playSessionBell() {
        if (!this._canPlay('session_bell', 1000)) return;
        try {
            this._initContext();
            if (!this.ctx) return;
            const now = this.ctx.currentTime;
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();

            osc.type = 'triangle';
            osc.frequency.setValueAtTime(523.25, now);
            osc.frequency.exponentialRampToValueAtTime(1046.50, now + 0.15);

            gain.gain.setValueAtTime(0.12, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);

            osc.connect(gain);
            gain.connect(this.ctx.destination);

            osc.start(now);
            osc.stop(now + 0.65);
        } catch (e) {
            console.warn("Audio bell error:", e);
        }
    }
}

window.audioManager = new AudioManager();
