(() => {
  const payload = window.attendanceCharts || {};
  if (typeof Chart === "undefined") return;
  Chart.defaults.color = "#9b9b9b";
  Chart.defaults.font.family = '"DM Sans", sans-serif';
  const grid = "rgba(255,255,255,.07)";
  const bars = { borderRadius: 4, borderSkipped: false };
  const subject = document.getElementById("subject-chart");
  if (subject) new Chart(subject, { type: "bar", data: { labels: payload.labels || [], datasets: [{ label: "Attendance %", data: payload.values || [], backgroundColor: "#dedede", ...bars }] }, options: { responsive: true, maintainAspectRatio: false, animation: { duration: 700 }, scales: { y: { beginAtZero: true, max: 100, grid: { color: grid }, ticks: { callback: (v) => `${v}%` } }, x: { grid: { display: false } } }, plugins: { legend: { display: false } } } });
  const trend = document.getElementById("trend-chart");
  if (trend) new Chart(trend, { type: "line", data: { labels: payload.trend_labels || [], datasets: [{ label: "Present", data: payload.present || [], borderColor: "#f2f2f2", backgroundColor: "#f2f2f214", fill: true, tension: .35, pointRadius: 2 }, { label: "Absent", data: payload.absent || [], borderColor: "#747474", backgroundColor: "transparent", tension: .35, pointRadius: 2 }] }, options: { responsive: true, maintainAspectRatio: false, animation: { duration: 700 }, scales: { y: { beginAtZero: true, grid: { color: grid } }, x: { grid: { display: false } } }, plugins: { legend: { labels: { usePointStyle: true, boxWidth: 6 } } } } });
  const ratio = document.getElementById("ratio-chart");
  if (ratio) new Chart(ratio, { type: "pie", data: { labels: ["Present", "Absent"], datasets: [{ data: [payload.present_total || 0, payload.absent_total || 0], backgroundColor: ["#e8e8e8", "#555"], borderColor: "#181818", borderWidth: 4 }] }, options: { responsive: true, maintainAspectRatio: false, animation: { duration: 700 }, plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 7, padding: 18 } } } } });
})();
