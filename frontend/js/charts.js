(function () {
  // Dark mode palette aligned with design system
  const GRID_COLOR = "rgba(255, 255, 255, 0.05)";
  const TICK_COLOR = "#52525b";
  const LEGEND_COLOR = "#a1a1aa";

  const CHART_DEFAULTS = {
    font: { family: "'Manrope', -apple-system, sans-serif", size: 11 },
    color: LEGEND_COLOR,
  };

  function destroyChart(chart) {
    if (chart) chart.destroy();
  }

  function buildTrainingLoadChart(canvas, trainingSeries, labels, sportColors) {
    if (!canvas || !trainingSeries?.length || !window.Chart) return null;

    // Set global Chart.js defaults for dark mode
    Chart.defaults.color = LEGEND_COLOR;

    return new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "CTL",
            data: trainingSeries.map((p) => p.ctl),
            borderColor: "#22d3ee",
            backgroundColor: "rgba(34,211,238,0.08)",
            tension: 0.35,
            pointRadius: 0,
            borderWidth: 2.5,
            fill: true,
          },
          {
            label: "ATL",
            data: trainingSeries.map((p) => p.atl),
            borderColor: "#f97316",
            backgroundColor: "rgba(249,115,22,0.06)",
            tension: 0.35,
            pointRadius: 0,
            borderWidth: 2,
            fill: true,
          },
          {
            label: "TSB",
            data: trainingSeries.map((p) => p.tsb),
            borderColor: "#a1a1aa",
            backgroundColor: "transparent",
            tension: 0.35,
            pointRadius: 0,
            borderWidth: 1.5,
            borderDash: [4, 3],
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: LEGEND_COLOR, boxWidth: 12, padding: 16, font: { size: 11, weight: "600" } },
          },
          tooltip: {
            backgroundColor: "#111",
            borderColor: "rgba(255,255,255,0.08)",
            borderWidth: 1,
            titleColor: "#a1a1aa",
            bodyColor: "#f4f4f5",
            padding: 10,
          },
        },
        scales: {
          x: {
            ticks: { maxTicksLimit: 8, color: TICK_COLOR, font: { size: 10 } },
            grid: { display: false },
            border: { display: false },
          },
          y: {
            ticks: { color: TICK_COLOR, font: { size: 10 } },
            grid: { color: GRID_COLOR },
            border: { display: false },
          },
        },
      },
    });
  }

  function buildVolumeChart(canvas, weeklyVolume, labels, sportColors, sportLabels) {
    if (!canvas || !weeklyVolume?.length || !window.Chart) return null;

    // Dark sport colors
    const darkSportColors = {
      running: "#22d3ee",
      cycling: "#f97316",
      swimming: "#3b82f6",
      climbing: "#ef4444",
      strength: "#71717a",
    };

    return new Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: Object.entries(darkSportColors).map(([sport, color]) => ({
          label: sportLabels[sport] || sport,
          data: weeklyVolume.map((week) => week.sports?.[sport]?.duration_min || 0),
          backgroundColor: color + "cc",
          borderRadius: 4,
          stack: "volume",
        })),
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: LEGEND_COLOR, boxWidth: 12, padding: 14, font: { size: 11, weight: "600" } },
          },
          tooltip: {
            backgroundColor: "#111",
            borderColor: "rgba(255,255,255,0.08)",
            borderWidth: 1,
            titleColor: "#a1a1aa",
            bodyColor: "#f4f4f5",
            padding: 10,
          },
        },
        scales: {
          x: {
            stacked: true,
            ticks: { color: TICK_COLOR, font: { size: 10 } },
            grid: { display: false },
            border: { display: false },
          },
          y: {
            stacked: true,
            ticks: { color: TICK_COLOR, font: { size: 10 } },
            grid: { color: GRID_COLOR },
            border: { display: false },
          },
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
          backgroundColor: ["#22d3ee", "#27272a", "#ef4444"],
          borderWidth: 0,
          hoverOffset: 4,
        }],
      },
      options: {
        maintainAspectRatio: false,
        cutout: "70%",
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: LEGEND_COLOR, boxWidth: 12, padding: 16, font: { size: 11, weight: "600" } },
          },
          tooltip: {
            backgroundColor: "#111",
            borderColor: "rgba(255,255,255,0.08)",
            borderWidth: 1,
            titleColor: "#a1a1aa",
            bodyColor: "#f4f4f5",
            padding: 10,
          },
        },
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
