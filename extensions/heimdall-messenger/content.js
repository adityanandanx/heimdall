(() => {
  const readUs = () => {
    const v = document.querySelector("video");
    return v ? Math.round(v.currentTime * 1e6) : null;
  };

  const send = () => {
    chrome.runtime.sendMessage({
      kind: "media",
      title: document.title,
      href: location.href,
      currentTimeUs: readUs(),
    }).catch(() => {});
  };

  document.addEventListener("yt-navigate-finish", send);
  setInterval(send, 1000);

  let lastTitle = document.title;
  new MutationObserver(() => {
    if (document.title !== lastTitle) {
      lastTitle = document.title;
      send();
    }
  }).observe(document, { subtree: true, childList: true });

  send();
})();
