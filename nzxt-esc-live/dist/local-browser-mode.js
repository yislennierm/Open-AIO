(function () {
  const version = "v6.05.11";
  try {
    if (new URLSearchParams(window.location.search).has("reset-designer")) {
      for (const key of Object.keys(window.localStorage)) {
        if (key.startsWith("nzxt-esc-dev:")) {
          window.localStorage.removeItem(key);
        }
      }
      window.history.replaceState(null, "", window.location.pathname);
    }
    window.localStorage.removeItem("nzxt-esc-dev:lastSeenReleaseNotesVersion");
  } catch {}

  const configuredVideos = new WeakSet();

  function configureLoopingVideo(video) {
    if (!(video instanceof HTMLVideoElement) || configuredVideos.has(video)) return;
    configuredVideos.add(video);

    video.loop = true;
    video.muted = true;
    video.autoplay = true;
    video.playsInline = true;
    video.preload = "auto";
    video.setAttribute("loop", "");
    video.setAttribute("muted", "");
    video.setAttribute("autoplay", "");
    video.setAttribute("playsinline", "");

    const resume = () => {
      const playResult = video.play();
      if (playResult && typeof playResult.catch === "function") {
        playResult.catch(() => {});
      }
    };

    video.addEventListener("pause", () => {
      if (!video.ended && !document.hidden) {
        window.setTimeout(resume, 20);
      }
    });
    video.addEventListener("ended", () => {
      try {
        video.currentTime = 0.001;
      } catch {}
      resume();
    });
    video.addEventListener("canplay", resume);
    resume();
  }

  function scanVideos() {
    document.querySelectorAll("video").forEach(configureLoopingVideo);
  }

  function smoothVideoLoops() {
    for (const video of document.querySelectorAll("video")) {
      configureLoopingVideo(video);
      if (!Number.isFinite(video.duration) || video.duration <= 0) continue;
      const remaining = video.duration - video.currentTime;
      if (remaining > 0 && remaining < 0.075) {
        try {
          video.currentTime = 0.001;
        } catch {}
      }
      if (video.paused && !video.ended && !document.hidden) {
        const playResult = video.play();
        if (playResult && typeof playResult.catch === "function") {
          playResult.catch(() => {});
        }
      }
    }
    window.requestAnimationFrame(smoothVideoLoops);
  }

  const observer = new MutationObserver(scanVideos);
  window.addEventListener("DOMContentLoaded", () => {
    scanVideos();
    observer.observe(document.documentElement, { childList: true, subtree: true });
    window.requestAnimationFrame(smoothVideoLoops);
  });

  function autoStartDevicePreview() {
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get("kraken") === "1" || params.get("noAutoDevicePreview") === "1") return;
      const button = document.querySelector(".device-preview-btn");
      if (!(button instanceof HTMLButtonElement) || button.classList.contains("active")) return;
      button.click();
    } catch {}
  }

  window.addEventListener("DOMContentLoaded", () => {
    const timer = window.setInterval(autoStartDevicePreview, 1000);
    window.setTimeout(() => window.clearInterval(timer), 30000);
    window.setTimeout(autoStartDevicePreview, 500);
    window.setTimeout(autoStartDevicePreview, 2000);
  });
})();
