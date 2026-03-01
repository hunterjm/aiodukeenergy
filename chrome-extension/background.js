/**
 * Duke Energy OAuth Helper - Background Service Worker
 *
 * This extension intercepts OAuth redirects from Duke Energy's Auth0 mobile
 * flow and extracts the authorization code. Two redirect patterns are handled:
 *
 *   - https://login.duke-energy.com/ios/... (iOS HTTPS redirect)
 *   - cma-prod://...                        (Android/legacy custom-scheme redirect)
 *
 * Both are caught in onBeforeNavigate.
 * onErrorOccurred catches cma-prod:// in case Chrome fires the error before the navigation is
 * intercepted.
 *
 * If the state parameter is a JWT containing a flow_id, it automatically
 * redirects to Home Assistant's OAuth endpoint.
 */

// Check if state is a JWT with flow_id (for Home Assistant)
function isHomeAssistantFlow(state) {
  if (!state) return false;
  try {
    // JWT has 3 parts separated by dots
    const parts = state.split(".");
    if (parts.length !== 3) return false;

    // Decode the payload (middle part)
    const payload = JSON.parse(atob(parts[1]));
    return payload && typeof payload.flow_id === "string";
  } catch (e) {
    return false;
  }
}

// Shared handler for both iOS and Android OAuth redirects.
function handleOAuthRedirect(tabId, url) {
  const urlObj = new URL(url);
  const code = urlObj.searchParams.get("code");
  const state = urlObj.searchParams.get("state");

  if (code && isHomeAssistantFlow(state)) {
    // Redirect to Home Assistant OAuth endpoint
    const haUrl = new URL("https://my.home-assistant.io/redirect/oauth");
    haUrl.searchParams.set("code", code);
    haUrl.searchParams.set("state", state);
    chrome.tabs.update(tabId, { url: haUrl.toString() });
    return;
  }

  // Otherwise, show capture page
  const captureUrl = new URL(chrome.runtime.getURL("capture.html"));
  captureUrl.searchParams.set("code", code || "");
  captureUrl.searchParams.set("state", state || "");
  captureUrl.searchParams.set("error", urlObj.searchParams.get("error") || "");
  captureUrl.searchParams.set(
    "error_description",
    urlObj.searchParams.get("error_description") || "",
  );

  if (code) {
    chrome.action.setBadgeText({ text: "✓" });
    chrome.action.setBadgeBackgroundColor({ color: "#4CAF50" });
  }

  chrome.tabs.update(tabId, { url: captureUrl.toString() });
}

// Catch Auth0 pushState URL changes (no real navigation fires onBeforeNavigate).
// This handles the case where Auth0's Universal Login uses history.pushState
// to update the address bar to the callback URL after credential validation,
// rather than issuing a real HTTP redirect.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  const url = changeInfo.url;
  if (url && url.startsWith("https://login.duke-energy.com/ios/")) {
    handleOAuthRedirect(tabId, url);
  }
});

// Intercept iOS HTTPS redirects and Android custom-scheme redirects before
// the browser attempts to load them (covers real page loads and refreshes).
chrome.webNavigation.onBeforeNavigate.addListener((details) => {
  const url = details.url;

  if (
    url.startsWith("https://login.duke-energy.com/ios/") ||
    url.startsWith("cma-prod://")
  ) {
    handleOAuthRedirect(details.tabId, url);
  }
});

// Fallback: catch cma-prod:// if Chrome fires onErrorOccurred before
// onBeforeNavigate can redirect the tab.
chrome.webNavigation.onErrorOccurred.addListener((details) => {
  if (details.url && details.url.startsWith("cma-prod://")) {
    handleOAuthRedirect(details.tabId, details.url);
  }
});
