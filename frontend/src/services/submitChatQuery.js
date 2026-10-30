export async function submitChatQuery(query, {
  prepare, send, browser = globalThis.navigator,
  now = () => performance.now(), reportTiming = (message) => console.info(message),
}) {
  const startedAt = now();
  let traceId = globalThis.crypto?.randomUUID?.() ?? "client";
  const log = (operation, start, status) => {
    const elapsed = now() - start;
    reportTiming(`[TIMING] operation=chat.client.${operation} status=${status} elapsed_s=${(elapsed / 1000).toFixed(3)} trace_id=${traceId}`);
  };
  const timed = async (operation, work) => {
    const start = now();
    let status = "success";
    try { return await work(); }
    catch (error) { status = "error"; throw error; }
    finally { log(operation, start, status); }
  };
  let status = "success";
  try {
    let preflight;
    try {
      preflight = await timed("preflight", async () => {
        const result = await prepare(query);
        traceId = result.traceId ?? traceId;
        return result;
      });
    } catch {
      return await timed("send", () => send(query, null));
    }
    if (!preflight.isFnb || !preflight.locationRequired) {
      return await timed("send", () => send(query, preflight.detectedLocation
        ? { source: "query", name: preflight.detectedLocation }
        : null));
    }
    const { location, denied } = await timed("location", () => browserLocation(browser));
    return await timed("send", () => denied === undefined ? send(query, location) : send(query, location, denied));
  } catch (error) {
    status = "error";
    throw error;
  } finally {
    log("total", startedAt, status);
  }
}

async function browserLocation(browser) {
  if (!browser?.geolocation) return { location: null, denied: true };

  let permission;
  try {
    permission = await browser.permissions?.query({ name: "geolocation" });
  } catch {
    // Some browsers support geolocation without the Permissions API.
  }
  if (permission?.state === "denied") return { location: null, denied: true };

  let position;
  try {
    position = await new Promise((resolve, reject) => {
      browser.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: false, timeout: 30000, maximumAge: 300000,
      });
    });
  } catch (error) {
    return { location: null, denied: error?.code === 1 };
  }
  return { location: {
    source: "browser",
    latitude: position.coords.latitude,
    longitude: position.coords.longitude,
  } };
}
