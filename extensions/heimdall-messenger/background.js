const HOST_NAME = "com.heimdall.messenger";
let port = null;

function connect() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
  } catch (e) {
    scheduleReconnect();
    return;
  }
  port.onMessage.addListener(() => {});
  port.onDisconnect.addListener(() => {
    port = null;
    scheduleReconnect();
  });
}

function scheduleReconnect() {
  setTimeout(connect, 2000);
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.kind === "media") {
    connect();
    if (port) {
      port.postMessage({
        title: msg.title,
        href: msg.href,
        currentTimeUs: msg.currentTimeUs,
      });
    }
  }
});

connect();
