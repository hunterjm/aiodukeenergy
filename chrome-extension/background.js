/**
 * Duke Energy OAuth Helper - Background Service Worker
 *
 * This extension intercepts the cma-prod:// redirect from Duke Energy's
 * Auth0 mobile OAuth flow and extracts the authorization code.
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

// Listen for navigation events that would redirect to cma-prod://
chrome.webNavigation.onBeforeNavigate.addListener(async (details) => {
  const url = details.url;

  // Check if this is the cma-prod:// redirect
  if (url.startsWith("https://login.duke-energy.com/ios/")) {
    // Parse the URL to extract the authorization code
    const urlObj = new URL(url);
    const code = urlObj.searchParams.get("code");
    const state = urlObj.searchParams.get("state");

    // Check if this is a Home Assistant flow
    if (code && isHomeAssistantFlow(state)) {
      // Redirect to Home Assistant OAuth endpoint
      const haUrl = new URL("https://my.home-assistant.io/redirect/oauth");
      haUrl.searchParams.set("code", code);
      haUrl.searchParams.set("state", state);

      chrome.tabs.update(details.tabId, { url: haUrl.toString() });
      return;
    }

    // Otherwise, show capture page
    const captureUrl = new URL(chrome.runtime.getURL("capture.html"));
    captureUrl.searchParams.set("code", code || "");
    captureUrl.searchParams.set("state", state || "");
    captureUrl.searchParams.set(
      "error",
      urlObj.searchParams.get("error") || "",
    );
    captureUrl.searchParams.set(
      "error_description",
      urlObj.searchParams.get("error_description") || "",
    );

    if (code) {
      chrome.action.setBadgeText({ text: "✓" });
      chrome.action.setBadgeBackgroundColor({ color: "#4CAF50" });
    }

    chrome.tabs.update(details.tabId, { url: captureUrl.toString() });
  }
});

// Also listen for errors when Chrome can't handle cma-prod://
chrome.webNavigation.onErrorOccurred.addListener(async (details) => {
  // Check if the error was for a cma-prod:// URL
  if (details.url && details.url.startsWith("https://login.duke-energy.com/ios/")) {
    const urlObj = new URL(details.url);
    const code = urlObj.searchParams.get("code");
    const state = urlObj.searchParams.get("state");

    // Check if this is a Home Assistant flow
    if (code && isHomeAssistantFlow(state)) {
      // Redirect to Home Assistant OAuth endpoint
      const haUrl = new URL("https://my.home-assistant.io/redirect/oauth");
      haUrl.searchParams.set("code", code);
      haUrl.searchParams.set("state", state);

      chrome.tabs.update(details.tabId, { url: haUrl.toString() });
      return;
    }

    // Otherwise, show capture page
    const captureUrl = new URL(chrome.runtime.getURL("capture.html"));
    captureUrl.searchParams.set("code", code || "");

    if (code) {
      chrome.action.setBadgeText({ text: "✓" });
      chrome.action.setBadgeBackgroundColor({ color: "#4CAF50" });
    }

    chrome.tabs.update(details.tabId, { url: captureUrl.toString() });
  }
});
