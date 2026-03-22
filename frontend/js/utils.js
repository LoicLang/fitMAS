(function () {
  function mapDayToApiKey(index) {
    return ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"][index];
  }

  function formatPace(avgSpeed) {
    if (!avgSpeed || avgSpeed <= 0) return null;
    const paceSeconds = 1000 / avgSpeed;
    const mins = Math.floor(paceSeconds / 60);
    const secs = Math.round(paceSeconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  function formatDistance(distanceM) {
    if (!distanceM || distanceM <= 0) return null;
    if (distanceM >= 1000) return `${(distanceM / 1000).toFixed(1)} km`;
    return `${Math.round(distanceM)} m`;
  }

  function formatWeekLabel(isoDate) {
    if (!isoDate) return "";
    return new Intl.DateTimeFormat("fr-FR", {
      day: "2-digit",
      month: "short",
    }).format(new Date(`${isoDate}T12:00:00Z`)).replace(".", "");
  }

  window.FitmasUtils = {
    formatDistance,
    formatPace,
    formatWeekLabel,
    mapDayToApiKey,
  };
})();
