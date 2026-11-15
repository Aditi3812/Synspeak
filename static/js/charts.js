// Charts manager using Chart.js with responsive bounded sizing
class ChartManager {
    constructor() {
        this.timelineChart = null;
        this.distributionChart = null;
        this.reportChart = null;
        
        this.maxTimelinePoints = 60; // 60 seconds of history
        this.timelineLabels = [];
        this.earData = [];
        this.marData = [];
        this.yawData = [];
    }

    initLiveCharts() {
        const ctxTimeline = document.getElementById('timelineChart')?.getContext('2d');
        const ctxDist = document.getElementById('distributionChart')?.getContext('2d');

        if (ctxTimeline) {
            this.timelineChart = new Chart(ctxTimeline, {
                type: 'line',
                data: {
                    labels: this.timelineLabels,
                    datasets: [
                        {
                            label: 'Avg EAR (Eyes)',
                            data: this.earData,
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.1)',
                            borderWidth: 2,
                            tension: 0.3,
                            fill: true,
                            yAxisID: 'yEar',
                            pointRadius: 0
                        },
                        {
                            label: 'MAR (Mouth/Yawn)',
                            data: this.marData,
                            borderColor: '#06b6d4',
                            backgroundColor: 'rgba(6, 182, 212, 0.08)',
                            borderWidth: 1.5,
                            borderDash: [3, 3],
                            tension: 0.3,
                            fill: false,
                            yAxisID: 'yEar',
                            pointRadius: 0
                        },
                        {
                            label: 'Head Yaw (°)',
                            data: this.yawData,
                            borderColor: '#6366f1',
                            backgroundColor: 'rgba(99, 102, 241, 0.05)',
                            borderWidth: 1.5,
                            tension: 0.3,
                            fill: false,
                            yAxisID: 'yYaw',
                            pointRadius: 0
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: {
                            labels: { color: '#94a3b8', boxWidth: 10, font: { size: 10 } }
                        },
                        tooltip: { enabled: true }
                    },
                    scales: {
                        x: {
                            display: true,
                            ticks: { color: '#64748b', maxTicksLimit: 6, font: { size: 9 } },
                            grid: { color: 'rgba(255, 255, 255, 0.04)' }
                        },
                        yEar: {
                            type: 'linear',
                            position: 'left',
                            min: 0,
                            max: 0.7,
                            ticks: { color: '#10b981', font: { size: 9 } },
                            grid: { color: 'rgba(255, 255, 255, 0.04)' },
                            title: { display: true, text: 'EAR / MAR', color: '#10b981', font: { size: 9 } }
                        },
                        yYaw: {
                            type: 'linear',
                            position: 'right',
                            min: -50,
                            max: 50,
                            ticks: { color: '#6366f1', font: { size: 9 } },
                            grid: { drawOnChartArea: false },
                            title: { display: true, text: 'Yaw (°)', color: '#6366f1', font: { size: 9 } }
                        }
                    }
                }
            });
        }

        if (ctxDist) {
            this.distributionChart = new Chart(ctxDist, {
                type: 'doughnut',
                data: {
                    labels: ['Focused', 'Phone', 'Head Turned', 'Eye Closure', 'Yawn', 'Absent'],
                    datasets: [{
                        data: [1, 0, 0, 0, 0, 0],
                        backgroundColor: [
                            '#10b981', // Focused (green)
                            '#ef4444', // Phone (red)
                            '#f59e0b', // Head turned (amber)
                            '#a855f7', // Eye closure (purple)
                            '#06b6d4', // Yawn (cyan)
                            '#64748b'  // Absent (slate)
                        ],
                        borderWidth: 2,
                        borderColor: '#0f172a'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '62%',
                    layout: {
                        padding: { top: 4, bottom: 4, left: 6, right: 6 }
                    },
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: {
                                color: '#94a3b8',
                                boxWidth: 10,
                                boxHeight: 10,
                                padding: 6,
                                font: { size: 10 }
                            }
                        }
                    }
                }
            });
        }
    }

    updateLiveCharts(telemetry) {
        const det = telemetry.detection;
        const ses = telemetry.session;
        if (!det || !ses) return;

        // Update Timeline
        const now = new Date();
        const timeLabel = `${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;
        
        this.timelineLabels.push(timeLabel);
        this.earData.push(det.avg_ear || 0);
        this.marData.push(det.mar || 0);
        this.yawData.push(det.head_yaw || 0);

        if (this.timelineLabels.length > this.maxTimelinePoints) {
            this.timelineLabels.shift();
            this.earData.shift();
            this.marData.shift();
            this.yawData.shift();
        }

        if (this.timelineChart) {
            this.timelineChart.update('none');
        }

        // Update Distribution Doughnut
        if (this.distributionChart) {
            const focused = ses.focused_seconds || 0;
            const phone = ses.phone_distracted_seconds || 0;
            const gaze = ses.gaze_distracted_seconds || 0;
            const drowsy = ses.drowsy_distracted_seconds || 0;
            const yawn = ses.yawn_distracted_seconds || 0;
            const absent = ses.absent_seconds || 0;

            const total = focused + phone + gaze + drowsy + yawn + absent;
            if (total > 0) {
                this.distributionChart.data.datasets[0].data = [focused, phone, gaze, drowsy, yawn, absent];
                this.distributionChart.update('none');
            }
        }
    }

    renderReportTimeline(containerId, timelineSamples) {
        const canvas = document.getElementById(containerId);
        if (!canvas || !timelineSamples || timelineSamples.length === 0) return;

        if (this.reportChart) {
            this.reportChart.destroy();
        }

        const labels = timelineSamples.map(s => `${Math.floor(s.t / 60)}m ${Math.floor(s.t % 60)}s`);
        const concData = timelineSamples.map(s => s.conc);
        const earData = timelineSamples.map(s => s.ear);
        const marData = timelineSamples.map(s => s.mar || 0);

        this.reportChart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Estimated Concentration (%)',
                        data: concData,
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.15)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.2,
                        yAxisID: 'yConc'
                    },
                    {
                        label: 'Avg EAR',
                        data: earData,
                        borderColor: '#38bdf8',
                        borderWidth: 1.5,
                        borderDash: [4, 4],
                        fill: false,
                        yAxisID: 'yEar'
                    },
                    {
                        label: 'MAR (Yawn)',
                        data: marData,
                        borderColor: '#06b6d4',
                        borderWidth: 1.5,
                        borderDash: [2, 2],
                        fill: false,
                        yAxisID: 'yEar'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { labels: { color: '#cbd5e1' } }
                },
                scales: {
                    x: {
                        ticks: { color: '#94a3b8', maxTicksLimit: 10 },
                        grid: { color: 'rgba(255, 255, 255, 0.05)' }
                    },
                    yConc: {
                        type: 'linear',
                        position: 'left',
                        min: 0,
                        max: 100,
                        ticks: { color: '#10b981' },
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        title: { display: true, text: 'Concentration %', color: '#10b981' }
                    },
                    yEar: {
                        type: 'linear',
                        position: 'right',
                        min: 0,
                        max: 0.6,
                        ticks: { color: '#38bdf8' },
                        grid: { drawOnChartArea: false },
                        title: { display: true, text: 'EAR / MAR', color: '#38bdf8' }
                    }
                }
            }
        });
    }
}

window.chartManager = new ChartManager();
