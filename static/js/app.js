// Synspeak Real-Time Concentration & Discipline Enforcement Application

class NotificationManager {
    constructor() {
        this.inAppEnabled = true;
        this.audioEnabled = true;
        this.browserEnabled = false;
        this.lastNotificationTime = 0;
        this.lastNotificationKey = '';
        this.checkInitialBrowserPermission();
    }

    checkInitialBrowserPermission() {
        if ('Notification' in window && Notification.permission === 'granted') {
            this.browserEnabled = true;
            const chk = document.getElementById('chkBrowserNotif');
            if (chk) chk.checked = true;
        }
    }

    async requestBrowserPermission() {
        if (!('Notification' in window)) {
            alert('This browser does not support desktop notifications.');
            return;
        }
        try {
            const perm = await Notification.requestPermission();
            if (perm === 'granted') {
                this.browserEnabled = true;
                const chk = document.getElementById('chkBrowserNotif');
                if (chk) chk.checked = true;
                this.showToast('Browser notifications enabled successfully!', 'success');
            } else {
                this.browserEnabled = false;
                const chk = document.getElementById('chkBrowserNotif');
                if (chk) chk.checked = false;
                this.showToast('Browser notification permission denied.', 'warning');
            }
        } catch (err) {
            console.warn('Error requesting notification permission:', err);
        }
    }

    notify(payload) {
        if (!payload) return;
        const msg = payload.message || 'Distraction alert';
        const title = payload.title || 'Synspeak Monitor';
        const severity = payload.severity || 'info';
        const audioCue = payload.audio || 'gentle_chime';

        // 1. In-App Notification (Toast & Banner)
        if (this.inAppEnabled) {
            this.showToast(msg, severity === 'punishment' || severity === 'critical' ? 'error' : (severity === 'warning' ? 'warning' : 'info'));
            this.showTopBanner(title, msg, severity);
        }

        // 2. Audio Notifications
        if (this.audioEnabled && window.audioManager) {
            switch (audioCue) {
                case 'minor_warning':
                case 'warning':
                    window.audioManager.playMinorWarning();
                    break;
                case 'critical':
                    window.audioManager.playCriticalWarning();
                    break;
                case 'major_alert':
                case 'punishment_activated':
                    window.audioManager.playPunishmentActivated();
                    break;
                case 'punishment_reset':
                    window.audioManager.playPunishmentReset();
                    break;
                case 'recovery_success':
                case 'punishment_completed':
                    window.audioManager.playRecoverySuccess();
                    break;
                case 'focus_reward':
                    window.audioManager.playFocusReward();
                    break;
                case 'session_bell':
                    window.audioManager.playSessionBell();
                    break;
                default:
                    window.audioManager.playGentleChime();
                    break;
            }
        }

        // 3. Desktop / Browser Notification (when page is backgrounded or tab inactive)
        if (this.browserEnabled && 'Notification' in window && Notification.permission === 'granted') {
            try {
                const n = new Notification(title, {
                    body: msg,
                    icon: '/favicon.ico',
                    tag: 'synspeak-distraction',
                    silent: true // sound is handled synthesized by Audio API
                });
                setTimeout(() => n.close(), 6000);
            } catch (e) {
                console.warn('Desktop notification error:', e);
            }
        }
    }

    showToast(msg, type = 'info') {
        const toast = document.getElementById('toast');
        if (!toast) return;
        toast.className = `toast toast-${type} show`;
        toast.textContent = msg;
        setTimeout(() => {
            if (toast.textContent === msg) {
                toast.className = 'toast';
            }
        }, 4000);
    }

    showTopBanner(title, msg, severity) {
        const banner = document.getElementById('topWarningBanner');
        const text = document.getElementById('topWarningText');
        if (!banner || !text) return;

        text.innerHTML = `<strong>${title}:</strong> ${msg}`;
        banner.className = `warning-banner-top ${severity}`;
        banner.style.display = 'flex';

        // Auto hide info/warning banners after 6s; critical/punishment stays until dismissed
        if (severity === 'info' || severity === 'warning') {
            setTimeout(() => {
                if (banner.className.includes(severity)) {
                    banner.style.display = 'none';
                }
            }, 6000);
        }
    }
}

class App {
    constructor() {
        this.video = document.getElementById('webcamVideo');
        this.overlayCanvas = document.getElementById('overlayCanvas');
        this.ctx = this.overlayCanvas.getContext('2d');
        
        // Offscreen canvas for frame capture
        this.captureCanvas = document.createElement('canvas');
        this.captureCtx = this.captureCanvas.getContext('2d');

        // Notification Manager
        this.notifManager = new NotificationManager();

        // WebSocket
        this.ws = null;
        this.wsConnected = false;
        this.isStreaming = false;
        this.frameTimer = null;
        this.targetFps = 20;
        this.isSendingFrame = false;
        this.isProcessingFrame = false;

        // Pomodoro Multi-Lap & Break Configuration
        this.pomConfig = {
            focusMinutes: 25,
            totalLaps: 4,
            breakMinutes: 5
        };

        // Session State
        this.sessionState = 'IDLE'; // IDLE, RUNNING, PAUSED, PUNISHMENT, COMPLETED
        this.goalMinutes = 25;
        this.lastAlertState = null;

        // Overlay Toggles
        this.toggles = {
            headPose: true,
            eyes: true,
            faceContour: true,
            phoneBoxes: true,
            mirror: true,
            audioAlert: true
        };

        // Cache last telemetry for rendering
        this.lastTelemetry = null;

        this.init();
    }

    init() {
        this.initTheme();
        this.initPomConfig();
        this.bindEvents();
        window.chartManager.initLiveCharts();
        this.initWebcam();
        this.connectWebSocket();
    }

    initTheme() {
        const savedTheme = localStorage.getItem('synspeak-theme') || 'dark';
        this.applyTheme(savedTheme);
    }

    toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || 'dark';
        const newTheme = current === 'dark' ? 'light' : 'dark';
        this.applyTheme(newTheme);
    }

    applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('synspeak-theme', theme);
        const icon = document.getElementById('themeToggleIcon');
        const text = document.getElementById('themeToggleText');
        if (icon) icon.textContent = theme === 'dark' ? '☀️' : '🌙';
        if (text) text.textContent = theme === 'dark' ? 'Light' : 'Dark';
    }

    bindEvents() {
        // Theme Toggle
        document.getElementById('btnThemeToggle')?.addEventListener('click', () => this.toggleTheme());

        // Session Controls
        document.getElementById('btnStart')?.addEventListener('click', () => this.startSession());
        document.getElementById('btnPause')?.addEventListener('click', () => this.togglePause());
        document.getElementById('btnStop')?.addEventListener('click', () => this.stopSession());
        document.getElementById('btnReset')?.addEventListener('click', () => this.resetSession());
        document.getElementById('btnCalibrate')?.addEventListener('click', () => this.calibrateGaze());

        // Goal selector change
        document.getElementById('goalSelect')?.addEventListener('change', (e) => {
            this.goalMinutes = parseInt(e.target.value, 10);
            this.updateGoalDisplay();
        });

        // Modals
        document.getElementById('btnSettings')?.addEventListener('click', () => this.openModal('settingsModal'));
        document.getElementById('btnEthicsInfo')?.addEventListener('click', () => this.openModal('ethicsModal'));
        document.getElementById('btnCloseSettings')?.addEventListener('click', () => this.closeModal('settingsModal'));
        document.getElementById('btnCloseEthics')?.addEventListener('click', () => this.closeModal('ethicsModal'));
        document.getElementById('btnCloseReport')?.addEventListener('click', () => this.closeModal('reportModal'));

        // Settings Sliders
        this.bindSettingSlider('sliderEar', 'valEar', 'ear_threshold', 2);
        this.bindSettingSlider('sliderDrowsy', 'valDrowsy', 'drowsy_duration_threshold', 1, 's');
        this.bindSettingSlider('sliderGaze', 'valGaze', 'gaze_duration_threshold', 1, 's');
        this.bindSettingSlider('sliderPhoneDur', 'valPhoneDur', 'phone_duration_threshold', 1, 's');
        this.bindSettingSlider('sliderAbsence', 'valAbsence', 'absence_duration_threshold', 0, 's');
        this.bindSettingSlider('sliderMouthArea', 'valMouthArea', 'mouth_area_threshold', 0);
        this.bindSettingSlider('sliderMaxFlags', 'valMaxFlags', 'max_flags_before_alert', 0);
        this.bindSettingSlider('sliderFlagWindow', 'valFlagWindow', 'flag_window_seconds', 0, 'm', 60);
        this.bindSettingSlider('sliderPunishDuration', 'valPunishDuration', 'punishment_duration_seconds', 0, 'm', 60);
        this.bindSettingSlider('sliderAllowedFlags', 'valAllowedFlags', 'punishment_max_flags', 0);

        // Notification Channel Toggles
        document.getElementById('chkInAppNotif')?.addEventListener('change', (e) => {
            this.notifManager.inAppEnabled = e.target.checked;
        });
        document.getElementById('chkAudioNotif')?.addEventListener('change', (e) => {
            this.notifManager.audioEnabled = e.target.checked;
            window.audioManager.enabled = e.target.checked;
        });
        document.getElementById('chkBrowserNotif')?.addEventListener('change', (e) => {
            if (e.target.checked) {
                this.notifManager.requestBrowserPermission();
            } else {
                this.notifManager.browserEnabled = false;
            }
        });
        document.getElementById('btnRequestBrowserNotif')?.addEventListener('click', () => {
            this.notifManager.requestBrowserPermission();
        });

        // Overlay Toggles
        document.getElementById('chkHeadPose')?.addEventListener('change', (e) => this.toggles.headPose = e.target.checked);
        document.getElementById('chkEyes')?.addEventListener('change', (e) => this.toggles.eyes = e.target.checked);
        document.getElementById('chkMesh')?.addEventListener('change', (e) => this.toggles.faceContour = e.target.checked);
        document.getElementById('chkPhone')?.addEventListener('change', (e) => this.toggles.phoneBoxes = e.target.checked);
        document.getElementById('chkAudio')?.addEventListener('change', (e) => {
            this.toggles.audioAlert = e.target.checked;
            this.notifManager.audioEnabled = e.target.checked;
            window.audioManager.enabled = e.target.checked;
        });
        document.getElementById('chkMirror')?.addEventListener('change', (e) => {
            this.toggles.mirror = e.target.checked;
            this.video.style.transform = e.target.checked ? 'scaleX(-1)' : 'none';
        });

        // Simulation / Test Feed Controls
        document.getElementById('btnStartSimulation')?.addEventListener('click', () => this.toggleTestFeed(true));
        document.getElementById('btnToggleSimFeed')?.addEventListener('click', () => this.toggleTestFeed());

        // Report Actions
        document.getElementById('btnDownloadReport')?.addEventListener('click', () => {
            window.location.href = '/api/export/report';
        });
        document.getElementById('btnPrintReport')?.addEventListener('click', () => window.print());
    }

    bindSettingSlider(sliderId, labelId, settingKey, decimals, suffix = '', multiplier = 1) {
        const slider = document.getElementById(sliderId);
        const label = document.getElementById(labelId);
        if (slider && label) {
            slider.addEventListener('input', (e) => {
                const rawVal = parseFloat(e.target.value);
                const sendVal = rawVal * multiplier;
                label.textContent = `${rawVal.toFixed(decimals)}${suffix}`;
                this.sendSettingsUpdate({ [settingKey]: sendVal });
            });
        }
    }

    async initWebcam() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 20 } },
                audio: false
            });
            this.video.srcObject = stream;
            this.video.onloadedmetadata = () => {
                this.video.play();
                const vw = this.video.videoWidth || 640;
                const vh = this.video.videoHeight || 480;
                this.overlayCanvas.width = vw;
                this.overlayCanvas.height = vh;

                // Ultra-low latency: cap capture to 320px wide; server scales boxes back up
                const maxW = 320;
                const captureScale = Math.min(1.0, maxW / vw);
                this.captureCanvas.width = Math.round(vw * captureScale);
                this.captureCanvas.height = Math.round(vh * captureScale);
                // Store scale factors so phone bboxes can be scaled to overlay coords
                this._captureScaleX = vw / this.captureCanvas.width;
                this._captureScaleY = vh / this.captureCanvas.height;
                this.startFrameStreaming();
            };
        } catch (err) {
            console.warn("Webcam access error or denied:", err);
            this.notifManager.showToast("Webcam unavailable. Check browser camera permissions.", "error");
            document.getElementById('cameraOverlayAlert').style.display = 'flex';
        }
    }

    toggleTestFeed(forceOn = false) {
        this.isSimulating = forceOn ? true : !this.isSimulating;
        const alertEl = document.getElementById('cameraOverlayAlert');
        if (alertEl) alertEl.style.display = 'none';

        if (this.isSimulating) {
            this.notifManager.showToast("Test Feed enabled: streaming test face to AI models.", "info");
            this.overlayCanvas.width = 640;
            this.overlayCanvas.height = 480;
            this.captureCanvas.width = 640;
            this.captureCanvas.height = 480;

            if (!this.testFaceImg) {
                this.testFaceImg = new Image();
                this.testFaceImg.src = '/static/images/test_face.jpg';
            }

            this.simTick = 0;
            if (this.frameTimer) clearInterval(this.frameTimer);
            this.frameTimer = setInterval(() => this.streamSimulatedFrame(), Math.round(1000 / this.targetFps));
        } else {
            this.notifManager.showToast("Returning to live camera mode.", "info");
            this.initWebcam();
        }
    }

    streamSimulatedFrame() {
        if (!this.wsConnected || this.isSendingFrame) return;
        this.simTick = (this.simTick || 0) + 1;

        this.captureCtx.fillStyle = '#0f172a';
        this.captureCtx.fillRect(0, 0, 640, 480);

        if (this.testFaceImg && this.testFaceImg.complete) {
            this.captureCtx.drawImage(this.testFaceImg, 96, 16, 448, 448);
        }

        this.isSendingFrame = true;
        this.captureCanvas.toBlob((blob) => {
            if (blob && this.wsConnected && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(blob);
            }
            this.isSendingFrame = false;
        }, 'image/jpeg', 0.82);
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.wsConnected = true;
            this.updateConnectionBadge(true);
            console.log("WebSocket connected to Synspeak server.");
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleServerMessage(data);
            } catch (err) {
                console.error("Error parsing WebSocket message:", err);
            }
        };

        this.ws.onclose = () => {
            this.wsConnected = false;
            this.updateConnectionBadge(false);
            console.warn("WebSocket disconnected. Retrying in 2 seconds...");
            setTimeout(() => this.connectWebSocket(), 2000);
        };

        this.ws.onerror = (err) => {
            console.error("WebSocket error:", err);
        };
    }

    updateConnectionBadge(connected) {
        const badge = document.getElementById('connBadge');
        if (badge) {
            badge.className = connected ? 'badge connected' : 'badge disconnected';
            badge.textContent = connected ? 'Live' : 'Connecting...';
        }
    }

    startFrameStreaming() {
        this.isStreaming = true;
        this.isProcessingFrame = false;
        if (this.frameTimer) clearInterval(this.frameTimer);
        
        // Flow control safety ticker: checks if a frame got lost
        this.frameTimer = setInterval(() => {
            if (this.isStreaming && !this.isProcessingFrame && !this.isSimulating) {
                this.sendNextFrame();
            }
        }, 100);

        this.sendNextFrame();
    }

    sendNextFrame() {
        if (!this.wsConnected || this.isProcessingFrame || !this.isStreaming || this.video.readyState < 2) return;

        this.isProcessingFrame = true;
        const vw = this.video.videoWidth || 640;
        const vh = this.video.videoHeight || 480;

        // Store scale factors so overlays can be scaled back up
        this._captureScaleX = vw / this.captureCanvas.width;
        this._captureScaleY = vh / this.captureCanvas.height;

        this.captureCtx.drawImage(this.video, 0, 0, this.captureCanvas.width, this.captureCanvas.height);

        this.captureCanvas.toBlob((blob) => {
            if (blob && this.wsConnected && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(blob);
            } else {
                this.isProcessingFrame = false;
            }
        }, 'image/jpeg', 0.70);
    }

    handleServerMessage(msg) {
        if (msg.type === 'telemetry') {
            this.lastTelemetry = msg;
            this.renderOverlays(msg.detection);
            this.updateTelemetryUI(msg);
            this.updateDisciplineUI(msg.session);
            this.updatePunishmentUI(msg.session.punishment, msg.session.pomodoro);
            window.chartManager.updateLiveCharts(msg);

            // Flow control: server finished processing, immediately request next real-time frame
            this.isProcessingFrame = false;
            if (this.isStreaming && !this.isSimulating) {
                requestAnimationFrame(() => this.sendNextFrame());
            }

            // Dispatch any queued notifications
            if (msg.session && msg.session.notifications && msg.session.notifications.length > 0) {
                for (const notif of msg.session.notifications) {
                    this.notifManager.notify(notif);
                }
            }
        } else if (msg.type === 'session_state') {
            this.sessionState = msg.status;
            this.updateSessionButtons();
            this.notifManager.showToast(msg.message, 'info');
        } else if (msg.type === 'report') {
            this.sessionState = 'COMPLETED';
            this.updateSessionButtons();
            this.displayReport(msg.report);
        } else if (msg.type === 'calibration_result') {
            if (msg.success) {
                this.notifManager.showToast(`Calibrated! Baseline Yaw: ${msg.baseline.baseline_yaw}°, Pitch: ${msg.baseline.baseline_pitch}°`, 'success');
            } else {
                this.notifManager.showToast(msg.baseline, 'warning');
            }
        }
    }

    renderOverlays(det) {
        const w = this.overlayCanvas.width;
        const h = this.overlayCanvas.height;
        this.ctx.clearRect(0, 0, w, h);

        if (!det) return;

        this.ctx.save();
        if (this.toggles.mirror) {
            this.ctx.translate(w, 0);
            this.ctx.scale(-1, 1);
        }

        // 1. Draw Key Face Contours
        if (this.toggles.faceContour && det.key_landmarks) {
            this.drawContour(det.key_landmarks.contour, w, h, 'rgba(148, 163, 184, 0.35)', 1);
            this.drawContour(det.key_landmarks.lips, w, h, 'rgba(244, 63, 94, 0.4)', 1);
        }

        // 2. Draw Eyes
        if (this.toggles.eyes && det.key_landmarks) {
            const eyeColor = det.eyes_closed ? '#a855f7' : '#10b981';
            this.drawContour(det.key_landmarks.left_eye, w, h, eyeColor, 2, true);
            this.drawContour(det.key_landmarks.right_eye, w, h, eyeColor, 2, true);
        }

        // 3. Draw 3D Head Orientation Gaze Vector (nose dot + direction)
        if (this.toggles.headPose && det.gaze_vector) {
            let ox, oy, tx, ty;
            if (det.gaze_vector.norm_origin) {
                ox = det.gaze_vector.norm_origin[0] * w;
                oy = det.gaze_vector.norm_origin[1] * h;
                tx = det.gaze_vector.norm_target[0] * w;
                ty = det.gaze_vector.norm_target[1] * h;
            } else if (det.key_landmarks && det.key_landmarks.nose && det.key_landmarks.nose.length > 0) {
                ox = det.key_landmarks.nose[0][0] * w;
                oy = det.key_landmarks.nose[0][1] * h;
                tx = ox;
                ty = oy;
            } else {
                ox = det.gaze_vector.origin[0];
                oy = det.gaze_vector.origin[1];
                tx = det.gaze_vector.target[0];
                ty = det.gaze_vector.target[1];
            }

            const isTurned = det.head_turned;
            const vectorColor = isTurned ? '#f59e0b' : '#38bdf8';

            // Nose tip anchor dot (drawn in mirrored coordinate space, exactly on the nose tip)
            this.ctx.beginPath();
            this.ctx.arc(ox, oy, 4, 0, 2 * Math.PI);
            this.ctx.fillStyle = vectorColor;
            this.ctx.fill();

            // Gaze arrow line
            this.ctx.beginPath();
            this.ctx.moveTo(ox, oy);
            this.ctx.lineTo(tx, ty);
            this.ctx.strokeStyle = vectorColor;
            this.ctx.lineWidth = 3;
            this.ctx.stroke();

            // Gaze target pointer dot
            this.ctx.beginPath();
            this.ctx.arc(tx, ty, 3, 0, 2 * Math.PI);
            this.ctx.fillStyle = '#ffffff';
            this.ctx.fill();
        }

        this.ctx.restore(); // Restore context to screen coordinates

        // 4. Draw Phone Bounding Boxes & Tags in screen space (so text is NOT mirrored!)
        if (this.toggles.phoneBoxes && det.phone_boxes && det.phone_boxes.length > 0) {
            for (const b of det.phone_boxes) {
                const nb = b.norm_bbox;
                let sx, sy, sw, sh;
                if (nb) {
                    if (this.toggles.mirror) {
                        // Video has CSS scaleX(-1), camera x maps to (1 - x) in screen space
                        sx = (1.0 - nb[2]) * w;
                        sw = (nb[2] - nb[0]) * w;
                    } else {
                        sx = nb[0] * w;
                        sw = (nb[2] - nb[0]) * w;
                    }
                    sy = nb[1] * h;
                    sh = (nb[3] - nb[1]) * h;
                } else if (b.bbox) {
                    const scaleX = w / (this.captureCanvas.width || 320);
                    const scaleY = h / (this.captureCanvas.height || 240);
                    let x1 = b.bbox[0] * scaleX;
                    let y1 = b.bbox[1] * scaleY;
                    let x2 = b.bbox[2] * scaleX;
                    let y2 = b.bbox[3] * scaleY;
                    if (this.toggles.mirror) {
                        sx = w - x2;
                        sw = x2 - x1;
                    } else {
                        sx = x1;
                        sw = x2 - x1;
                    }
                    sy = y1;
                    sh = y2 - y1;
                } else {
                    continue;
                }

                this.ctx.strokeStyle = '#ef4444';
                this.ctx.lineWidth = 3;
                this.ctx.strokeRect(sx, sy, sw, sh);

                // Phone label banner (regular forward-facing text)
                const tagH = 24;
                const tagW = 145;
                const tagY = Math.max(0, sy - tagH);
                this.ctx.fillStyle = 'rgba(239, 68, 68, 0.95)';
                this.ctx.fillRect(sx, tagY, tagW, tagH);
                this.ctx.fillStyle = '#ffffff';
                this.ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
                this.ctx.fillText(`📱 Phone ${Math.round(b.confidence * 100)}%`, sx + 6, tagY + 16);
            }
        }
    }

    drawContour(points, w, h, strokeColor, lineWidth = 1, fill = false) {
        if (!points || points.length === 0) return;
        this.ctx.beginPath();
        this.ctx.moveTo(points[0][0] * w, points[0][1] * h);
        for (let i = 1; i < points.length; i++) {
            this.ctx.lineTo(points[i][0] * w, points[i][1] * h);
        }
        this.ctx.closePath();
        this.ctx.strokeStyle = strokeColor;
        this.ctx.lineWidth = lineWidth;
        this.ctx.stroke();
        if (fill) {
            this.ctx.fillStyle = strokeColor + '33';
            this.ctx.fill();
        }
    }

    updateTelemetryUI(telemetry) {
        const det = telemetry.detection;
        const ses = telemetry.session;

        // 1. Current State Floating Badge
        const stateBadge = document.getElementById('stateBadge');
        if (stateBadge) {
            const stateConfig = this.getStateConfig(ses.current_state);
            stateBadge.className = `state-badge ${stateConfig.className}`;
            stateBadge.innerHTML = `<span class="dot"></span> ${stateConfig.label} <small>(${ses.current_state_duration_s}s)</small>`;
        }

        // 2. Concentration Gauge
        const concVal = document.getElementById('concPercentage');
        const concCircle = document.getElementById('concCircle');
        if (concVal) {
            concVal.textContent = `${Math.round(ses.concentration_percentage)}%`;
        }
        if (concCircle) {
            const circumference = 2 * Math.PI * 45;
            const offset = circumference - (ses.concentration_percentage / 100) * circumference;
            concCircle.style.strokeDashoffset = offset;
            concCircle.style.stroke = ses.concentration_percentage >= 80 ? '#10b981' : (ses.concentration_percentage >= 60 ? '#f59e0b' : '#ef4444');
        }

        // 3. Durations
        this.setText('lblFocusedTime', this.formatSeconds(ses.focused_seconds));
        this.setText('lblDistractedTime', this.formatSeconds(ses.distracted_seconds));
        this.setText('lblAbsentTime', this.formatSeconds(ses.absent_seconds));
        this.setText('lblTotalTime', this.formatSeconds(ses.total_elapsed_seconds));
        this.setText('lblEventCount', `${ses.distraction_event_count} events`);

        // Goal Progress
        if (this.goalMinutes > 0 && this.sessionState === 'RUNNING') {
            const totalGoalSec = this.goalMinutes * 60;
            const progressPct = Math.min(100, (ses.focused_seconds / totalGoalSec) * 100);
            const goalBar = document.getElementById('goalProgressBar');
            if (goalBar) goalBar.style.width = `${progressPct}%`;
            this.setText('lblGoalRemaining', `${Math.max(0, Math.ceil((totalGoalSec - ses.focused_seconds) / 60))}m remaining`);
        }

        // 4. Biometric Telemetry
        this.setText('lblEarLeft', det.left_ear.toFixed(3));
        this.setText('lblEarRight', det.right_ear.toFixed(3));
        this.setText('lblEarAvg', det.avg_ear.toFixed(3));
        this.setText('lblPoseYaw', `${det.head_yaw > 0 ? '+' : ''}${det.head_yaw}°`);
        this.setText('lblPosePitch', `${det.head_pitch > 0 ? '+' : ''}${det.head_pitch}°`);
        this.setText('lblInferenceFps', `${det.inference_time_ms} ms`);

        // EAR Meter Bar
        const earBar = document.getElementById('earBarFill');
        if (earBar) {
            const earPct = Math.min(100, (det.avg_ear / 0.45) * 100);
            earBar.style.width = `${earPct}%`;
            earBar.style.background = det.eyes_closed ? '#a855f7' : '#10b981';
        }

        // Update Events Table
        this.updateEventsTable(ses.recent_events, ses.active_event);
    }

    updateDisciplineUI(session) {
        if (!session) return;

        // Discipline Score (100-pt)
        if (session.discipline) {
            const score = session.discipline.score;
            const scoreEl = document.getElementById('lblDisciplineScore');
            if (scoreEl) {
                scoreEl.textContent = `${score} / 100`;
                scoreEl.className = `disc-hero-val ${score >= 80 ? 'score-high' : (score >= 60 ? 'score-mid' : 'score-low')}`;
            }
            this.setText('lblTotalDeductions', `-${session.discipline.total_deducted}`);
            this.setText('lblTotalRewards', `+${session.discipline.total_rewarded}`);

            // Focus Streak
            this.setText('lblFocusStreak', this.formatSeconds(session.discipline.focus_streak_seconds));
            this.setText('lblLongestStreak', this.formatSeconds(session.discipline.longest_streak_seconds));
            // lblQualifiedFocus removed from UI; skip safely if element absent
            const qualEl = document.getElementById('lblQualifiedFocus');
            if (qualEl) qualEl.textContent = this.formatSeconds(session.discipline.total_qualified_focus_seconds);
        }

        // Distraction Flags & 5-dot strip
        if (session.flags) {
            const cycleFlags = session.flags.cycle_flags || 0;
            this.setText('lblFlagsCount', `${cycleFlags} flags`);
            this.setText('lblFlagsRemaining', `${session.flags.flags_until_punishment} left`);

            for (let i = 1; i <= 5; i++) {
                const dot = document.getElementById(`dotFlag${i}`);
                if (dot) {
                    if (cycleFlags >= i) {
                        dot.classList.add('active');
                    } else {
                        dot.classList.remove('active');
                    }
                }
            }
        }

        // Pomodoro Status
        if (session.pomodoro) {
            const pom = session.pomodoro;
            this.setText('lblPomodoroTimer', this.formatSeconds(pom.remaining_seconds));
            this.setText('lblPomodoroState', pom.state);

            const frozenEl = document.getElementById('lblPomodoroFrozenNotice');
            if (frozenEl) frozenEl.style.display = pom.is_frozen ? 'inline' : 'none';

            // Top bar time + meta
            this.setText('lblPomodoroBarTime', this.formatSeconds(pom.remaining_seconds));
            this.setText('lblPomodoroBarRemaining', this.formatSeconds(pom.remaining_seconds));
            this.setText('lblPomodoroBarElapsed', this.formatSeconds(pom.elapsed_seconds));

            // Lap counter e.g. "Lap 2 of 4"
            this.setText('lblPomodoroBarLap', `Lap ${pom.current_lap} of ${pom.total_laps}`);

            // Phase: FOCUS or BREAK with color
            const phaseEl = document.getElementById('lblPomodoroBarPhase');
            if (phaseEl) {
                if (pom.is_break) {
                    phaseEl.textContent = '☕ BREAK';
                    phaseEl.style.color = 'var(--accent-cyan)';
                } else {
                    phaseEl.textContent = 'FOCUS';
                    phaseEl.style.color = 'var(--accent-emerald)';
                }
            }

            // Status tag
            const barStatus = document.getElementById('lblPomodoroBarStatus');
            if (barStatus) {
                barStatus.textContent = pom.state;
                barStatus.className = `pom-status-tag status-${pom.state.toLowerCase()}`;
            }

            const barFrozenNotice = document.getElementById('lblPomodoroBarFrozenNotice');
            if (barFrozenNotice) {
                barFrozenNotice.style.display = pom.is_frozen ? 'inline-block' : 'none';
            }

            const barFill = document.getElementById('pomodoroBarFill');
            if (barFill) {
                barFill.style.width = `${pom.progress_pct}%`;
                barFill.className = `pom-progress-fill${pom.is_frozen ? ' frozen' : ''}${pom.is_break ? ' break' : ''}`;
            }

            // Update config summary label to reflect live config
            this.setText('lblPomConfigSummary', `${pom.lap_minutes}m × ${pom.total_laps} Laps (${pom.break_minutes}m Break)`);
        }
    }

    updatePunishmentUI(punishment, pomodoro) {
        const heroPanel = document.getElementById('punishmentHeroPanel');
        if (!heroPanel) return;

        if (punishment && punishment.is_active) {
            heroPanel.style.display = 'block';

            // Large countdown
            this.setText('punishCountdown', this.formatSeconds(punishment.remaining_seconds));

            // Progress bar
            const bar = document.getElementById('punishProgressBar');
            if (bar) bar.style.width = `${punishment.progress_pct}%`;

            // Frozen Pomodoro
            if (pomodoro) {
                this.setText('punishFrozenPomodoro', this.formatSeconds(pomodoro.remaining_seconds));
            } else if (punishment.frozen_pomodoro_remaining !== null) {
                this.setText('punishFrozenPomodoro', this.formatSeconds(punishment.frozen_pomodoro_remaining));
            }

            // Allowed flags
            this.setText('punishAllowedFlags', `${punishment.punishment_flags} / ${punishment.max_flags_allowed} max`);

            // Resets count
            this.setText('punishResetCount', `${punishment.reset_count} resets`);
        } else {
            heroPanel.style.display = 'none';
        }
    }

    updateEventsTable(recentEvents, activeEvent) {
        const tbody = document.getElementById('eventsTableBody');
        if (!tbody) return;

        let rows = '';
        if (activeEvent) {
            rows += `
                <tr class="active-event-row">
                    <td><span class="pulse-dot"></span> LIVE</td>
                    <td><span class="badge ${activeEvent.category}">${activeEvent.reason}</span></td>
                    <td>${activeEvent.start_time}</td>
                    <td><strong>${activeEvent.duration_s}s</strong></td>
                    <td><small>${activeEvent.peak_detail || '-'}</small></td>
                </tr>
            `;
        }

        if (recentEvents && recentEvents.length > 0) {
            for (let i = recentEvents.length - 1; i >= 0; i--) {
                const ev = recentEvents[i];
                rows += `
                    <tr>
                        <td>#${ev.id}</td>
                        <td><span class="badge ${ev.category}">${ev.reason}</span></td>
                        <td>${ev.start_time}</td>
                        <td>${ev.duration_s}s</td>
                        <td><small>${ev.peak_detail || '-'}</small></td>
                    </tr>
                `;
            }
        }

        if (!rows) {
            rows = '<tr><td colspan="5" class="empty-state">No distraction patterns observed yet. Excellent focus!</td></tr>';
        }
        tbody.innerHTML = rows;
    }

    getStateConfig(state) {
        switch (state) {
            case 'FOCUSED':
                return { label: 'Focused Engagement', className: 'state-focused' };
            case 'DISTRACTED_PHONE':
                return { label: 'Mobile Phone Visible', className: 'state-phone' };
            case 'DISTRACTED_GAZE':
                return { label: 'Head Turned Away', className: 'state-gaze' };
            case 'DISTRACTED_DROWSY':
                return { label: 'Prolonged Eye Closure', className: 'state-drowsy' };
            case 'DISTRACTED_YAWN':
                return { label: 'Yawning Observed', className: 'state-yawn' };
            case 'ABSENT':
                return { label: 'Desk Absence', className: 'state-absent' };
            default:
                return { label: 'Unclassified / Occluded', className: 'state-unknown' };
        }
    }

    initPomConfig() {
        const saved = localStorage.getItem('synspeak_pom_config');
        if (saved) {
            try {
                this.pomConfig = JSON.parse(saved);
            } catch (e) {
                this.pomConfig = { focusMinutes: 25, totalLaps: 4, breakMinutes: 5 };
            }
        } else {
            this.pomConfig = { focusMinutes: 25, totalLaps: 4, breakMinutes: 5 };
        }

        this.updatePomConfigUI();

        // Bind Open Modal Button
        document.getElementById('btnOpenPomConfig')?.addEventListener('click', () => {
            this.syncPomInputs();
            const modal = document.getElementById('pomConfigModal');
            if (modal) modal.style.display = 'flex';
        });

        // Input changes live update preview
        ['inpFocusMinutes', 'inpTotalLaps', 'inpBreakMinutes'].forEach(id => {
            document.getElementById(id)?.addEventListener('input', () => this.updatePomPreview());
        });

        // Save & Apply
        document.getElementById('btnSavePomConfig')?.addEventListener('click', () => {
            const focus = parseInt(document.getElementById('inpFocusMinutes')?.value, 10) || 25;
            const laps = parseInt(document.getElementById('inpTotalLaps')?.value, 10) || 1;
            const brk = parseInt(document.getElementById('inpBreakMinutes')?.value, 10) || 0;

            this.pomConfig = {
                focusMinutes: Math.max(1, focus),
                totalLaps: Math.max(1, laps),
                breakMinutes: Math.max(0, brk)
            };
            this.goalMinutes = this.pomConfig.focusMinutes;
            localStorage.setItem('synspeak_pom_config', JSON.stringify(this.pomConfig));
            this.updatePomConfigUI();

            const modal = document.getElementById('pomConfigModal');
            if (modal) modal.style.display = 'none';

            this.notifManager.showToast(`Pomodoro configured: ${this.pomConfig.focusMinutes}m × ${this.pomConfig.totalLaps} laps (${this.pomConfig.breakMinutes}m break)`, 'success');
        });
    }

    applyPomPreset(focus, laps, brk) {
        const inFocus = document.getElementById('inpFocusMinutes');
        const inLaps = document.getElementById('inpTotalLaps');
        const inBrk = document.getElementById('inpBreakMinutes');
        if (inFocus) inFocus.value = focus;
        if (inLaps) inLaps.value = laps;
        if (inBrk) inBrk.value = brk;
        this.updatePomPreview();
    }

    syncPomInputs() {
        const inFocus = document.getElementById('inpFocusMinutes');
        const inLaps = document.getElementById('inpTotalLaps');
        const inBrk = document.getElementById('inpBreakMinutes');
        if (inFocus) inFocus.value = this.pomConfig.focusMinutes;
        if (inLaps) inLaps.value = this.pomConfig.totalLaps;
        if (inBrk) inBrk.value = this.pomConfig.breakMinutes;
        this.updatePomPreview();
    }

    updatePomPreview() {
        const focus = parseInt(document.getElementById('inpFocusMinutes')?.value, 10) || 25;
        const laps = parseInt(document.getElementById('inpTotalLaps')?.value, 10) || 1;
        const brk = parseInt(document.getElementById('inpBreakMinutes')?.value, 10) || 0;

        const totalFocus = focus * laps;
        const totalBreak = brk * Math.max(0, laps - 1);
        const totalSession = totalFocus + totalBreak;

        this.setText('prevTotalFocus', `${totalFocus} min`);
        this.setText('prevTotalBreak', `${totalBreak} min`);
        this.setText('prevTotalSession', `${totalSession} min`);
    }

    updatePomConfigUI() {
        const summary = `${this.pomConfig.focusMinutes}m × ${this.pomConfig.totalLaps} Laps (${this.pomConfig.breakMinutes}m Break)`;
        this.setText('lblPomConfigSummary', summary);
        this.setText('lblPomodoroBarTime', this.formatSeconds(this.pomConfig.focusMinutes * 60));
        this.setText('lblPomodoroBarRemaining', this.formatSeconds(this.pomConfig.focusMinutes * 60));
        this.setText('lblPomodoroBarLap', `Lap 1 of ${this.pomConfig.totalLaps}`);
    }

    startSession() {
        if (!this.wsConnected) {
            this.notifManager.showToast("Server disconnected. Reconnecting...", "error");
            return;
        }
        this.ws.send(JSON.stringify({
            type: 'start',
            lap_minutes: this.pomConfig.focusMinutes,
            total_laps: this.pomConfig.totalLaps,
            break_minutes: this.pomConfig.breakMinutes,
            goal_minutes: this.pomConfig.focusMinutes
        }));
        if (window.audioManager) window.audioManager.playSessionBell();
        this.sessionState = 'RUNNING';
        this.updateSessionButtons();
        this.notifManager.showToast(`Pomodoro started: ${this.pomConfig.focusMinutes}m × ${this.pomConfig.totalLaps} laps (${this.pomConfig.breakMinutes}m break)`, 'success');
    }

    togglePause() {
        if (this.sessionState === 'RUNNING') {
            this.ws.send(JSON.stringify({ type: 'pause' }));
            this.sessionState = 'PAUSED';
        } else if (this.sessionState === 'PAUSED') {
            this.ws.send(JSON.stringify({ type: 'resume' }));
            this.sessionState = 'RUNNING';
        }
        this.updateSessionButtons();
    }

    stopSession() {
        if (this.wsConnected) {
            this.ws.send(JSON.stringify({ type: 'stop' }));
        }
    }

    resetSession() {
        if (confirm("Reset current session data and start fresh?")) {
            if (this.wsConnected) {
                this.ws.send(JSON.stringify({ type: 'reset' }));
            }
            this.sessionState = 'IDLE';
            this.updateSessionButtons();
            this.notifManager.showToast("Session reset to initial state.", "info");
        }
    }

    calibrateGaze() {
        if (!this.wsConnected) return;
        this.notifManager.showToast("Calibrating... Look directly at the screen naturally.", "info");
        this.ws.send(JSON.stringify({ type: 'calibrate' }));
    }

    sendSettingsUpdate(newSettings) {
        if (this.wsConnected) {
            this.ws.send(JSON.stringify({
                type: 'update_settings',
                settings: newSettings
            }));
        }
    }

    updateSessionButtons() {
        const btnStart = document.getElementById('btnStart');
        const btnPause = document.getElementById('btnPause');
        const btnStop = document.getElementById('btnStop');

        if (this.sessionState === 'RUNNING') {
            btnStart.disabled = true;
            btnPause.disabled = false;
            btnPause.innerHTML = '<span>⏸</span> Pause';
            btnStop.disabled = false;
        } else if (this.sessionState === 'PAUSED') {
            btnStart.disabled = true;
            btnPause.disabled = false;
            btnPause.innerHTML = '<span>▶</span> Resume';
            btnStop.disabled = false;
        } else {
            btnStart.disabled = false;
            btnPause.disabled = true;
            btnPause.innerHTML = '<span>⏸</span> Pause';
            btnStop.disabled = true;
        }
    }

    displayReport(report) {
        this.openModal('reportModal');

        this.setText('repSessionId', report.session_id);
        this.setText('repStart', report.timestamps.start);
        this.setText('repEnd', report.timestamps.end);
        this.setText('repTotalDuration', report.durations.total_formatted);
        this.setText('repConcentrationScore', `${report.percentages.concentration_score}%`);

        this.setText('repFocusedTime', `${report.durations.focused_formatted} (${report.percentages.focused_ratio}%)`);
        this.setText('repDistractedTime', `${report.durations.distracted_formatted} (${report.percentages.distracted_ratio}%)`);
        this.setText('repAbsentTime', `${report.durations.absent_formatted} (${report.percentages.absent_ratio}%)`);
        this.setText('repUnknownTime', `${report.durations.unknown_formatted} (${report.percentages.unknown_ratio}%)`);

        // Discipline & Accountability Section
        if (report.discipline_summary) {
            const ds = report.discipline_summary;
            this.setText('repDisciplineScore', `${ds.final_score} / 100`);
            this.setText('repTotalDeductions', `-${ds.total_deductions} pts`);
            this.setText('repLongestStreak', ds.longest_focus_streak_formatted);
        }

        if (report.flags_summary) {
            this.setText('repTotalFlags', `${report.flags_summary.total_flags} flags`);
        }

        if (report.punishment_summary) {
            const ps = report.punishment_summary;
            this.setText('repTotalPunishments', `${ps.total_punishments_triggered}`);
            this.setText('repPunishmentTime', `${ps.total_punishment_time_served_formatted} (${ps.total_resets} resets)`);
        }

        // Breakdown counts
        const bd = report.distraction_breakdown;
        this.setText('repPhoneStats', `${bd.phone.formatted} (${bd.phone.events_count} events)`);
        this.setText('repGazeStats', `${bd.gaze.formatted} (${bd.gaze.events_count} events)`);
        this.setText('repDrowsyStats', `${bd.drowsy.formatted} (${bd.drowsy.events_count} events)`);
        this.setText('repYawnStats', `${bd.yawn.formatted} (${bd.yawn.events_count} events)`);
        this.setText('repAbsenceStats', `${bd.absence.formatted} (${bd.absence.events_count} events)`);

        // Insights Cards
        const insightsContainer = document.getElementById('repInsightsContainer');
        if (insightsContainer && report.insights) {
            insightsContainer.innerHTML = report.insights.map(ins => `
                <div class="insight-card ${ins.type}">
                    <h4>${ins.title}</h4>
                    <p>${ins.detail}</p>
                </div>
            `).join('');
        }

        // Render Report Timeline Chart
        window.chartManager.renderReportTimeline('reportTimelineCanvas', report.timeline_samples);

        // Chronological Event History Table
        const repEventsTbody = document.getElementById('repEventsTableBody');
        if (repEventsTbody) {
            const timeline = (report.events_summary && report.events_summary.chronological_timeline)
                ? report.events_summary.chronological_timeline
                : [];

            if (timeline.length > 0) {
                repEventsTbody.innerHTML = timeline.map(item => `
                    <tr>
                        <td><strong>${item.timestamp || '-'}</strong></td>
                        <td>${item.description}</td>
                        <td>${item.duration_s ? item.duration_s + 's' : '-'}</td>
                        <td>${item.penalty ? '<span style="color: var(--accent-rose); font-weight: bold;">-' + item.penalty + ' pts</span>' : (item.flag_id ? '<span style="color: var(--accent-amber);">Flag #' + item.flag_id + '</span>' : '-')}</td>
                    </tr>
                `).join('');
            } else if (report.events_summary && report.events_summary.all_events && report.events_summary.all_events.length > 0) {
                repEventsTbody.innerHTML = report.events_summary.all_events.map(ev => `
                    <tr>
                        <td>${ev.start_time}</td>
                        <td><span class="badge ${ev.category}">${ev.reason}</span></td>
                        <td>${ev.duration_s}s</td>
                        <td>${ev.penalty ? '-' + ev.penalty + ' pts' : '-'}</td>
                    </tr>
                `).join('');
            } else {
                repEventsTbody.innerHTML = '<tr><td colspan="4" class="empty-state">No distraction events occurred during this session. Outstanding focus!</td></tr>';
            }
        }
    }

    openModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'flex';
    }

    closeModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'none';
    }

    setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    formatSeconds(s) {
        const sec = Math.floor(s || 0);
        const m = Math.floor(sec / 60);
        const remSec = sec % 60;
        return `${m.toString().padStart(2, '0')}:${remSec.toString().padStart(2, '0')}`;
    }

    updateGoalDisplay() {
        this.setText('lblGoalDuration', `${this.goalMinutes}m`);
    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.app = new App();
});
