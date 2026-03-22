(function () {
  function destroyChart(chart) {
    if (chart) chart.destroy();
  }

  function buildTrainingLoadChart(canvas, trainingSeries, labels, sportColors) {
    if (!canvas || !trainingSeries?.length || !window.Chart) return null;
    return new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "CTL", data: trainingSeries.map((point) => point.ctl), borderColor: sportColors.running, backgroundColor: "rgba(15,118,110,0.12)", tension: 0.28, pointRadius: 0, borderWidth: 2.5 },
          { label: "ATL", data: trainingSeries.map((point) => point.atl), borderColor: sportColors.cycling, backgroundColor: "rgba(194,107,59,0.10)", tension: 0.28, pointRadius: 0, borderWidth: 2.5 },
          { label: "TSB", data: trainingSeries.map((point) => point.tsb), borderColor: sportColors.swimming, backgroundColor: "rgba(37,99,235,0.10)", tension: 0.28, pointRadius: 0, borderWidth: 2 },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
        scales: {
          x: { ticks: { maxTicksLimit: 8, color: "#6c584a" }, grid: { display: false } },
          y: { ticks: { color: "#6c584a" }, grid: { color: "rgba(69,47,32,0.08)" } },
        },
      },
    });
  }

  function buildVolumeChart(canvas, weeklyVolume, labels, sportColors, sportLabels) {
    if (!canvas || !weeklyVolume?.length || !window.Chart) return null;
    return new Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: Object.entries(sportColors).map(([sport, color]) => ({
          label: sportLabels[sport],
          data: weeklyVolume.map((week) => week.sports?.[sport]?.duration_min || 0),
          backgroundColor: color,
          borderRadius: 6,
          stack: "volume",
        })),
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
        scales: {
          x: { stacked: true, ticks: { color: "#6c584a" }, grid: { display: false } },
          y: { stacked: true, ticks: { color: "#6c584a" }, grid: { color: "rgba(69,47,32,0.08)" } },
        },
      },
    });
  }

  function buildCompletionChart(canvas, doneCount, plannedCount, skippedCount) {
    if (!canvas || !window.Chart) return null;
    return new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: ["Fait", "À faire", "Sauté"],
        datasets: [{
          data: [doneCount, plannedCount, skippedCount],
          backgroundColor: ["#16a34a", "#0f766e", "#dc2626"],
          borderWidth: 0,
        }],
      },
      options: {
        maintainAspectRatio: false,
        cutout: "68%",
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  window.FitmasCharts = {
    buildCompletionChart,
    buildTrainingLoadChart,
    buildVolumeChart,
    destroyChart,
  };
})();
