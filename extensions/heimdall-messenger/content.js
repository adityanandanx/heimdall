(() => {
  const readUs = () => {
    const v = document.querySelector("video");
    return v ? Math.round(v.currentTime * 1e6) : null;
  };

  const send = () => {
    // Only the visible tab speaks: the daemon attributes a URL to frames by
    // title recency, and hidden tabs would drown the stream with stale rows.
    if (document.visibilityState !== "visible") return;
    chrome.runtime.sendMessage({
      kind: "media",
      title: document.title,
      href: location.href,
      currentTimeUs: readUs(),
    }).catch(() => {});
  };

  document.addEventListener("visibilitychange", send);
  setInterval(send, 1000);

  let lastTitle = ""; // always send the first sighting
  new MutationObserver(() => {
    if (document.title !== lastTitle && document.visibilityState === "visible") {
      lastTitle = document.title;
      send();
    }
  }).observe(document, { subtree: true, childList: true });

  send();
})();
