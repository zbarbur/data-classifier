// Worker pool — size 2, lazy init, eager respawn on timeout, MV3-aware.
// The spawn function is injected so tests can mock it; in production, callers
// pass () => new Worker(new URL('./worker.js', import.meta.url), {type:'module'}).

export function createPool({ size = 2, spawn }) {
  const workers = []; // { worker, busy, listeners }
  const queue = [];
  let nextId = 0;

  function getFreeWorker() {
    for (const slot of workers) if (!slot.busy) return slot;
    if (workers.length < size) {
      const slot = { worker: spawn(), busy: false, listeners: new Map() };
      slot.worker.addEventListener('message', (event) => {
        const { id, result, error } = event.data || {};
        const resolver = slot.listeners.get(id);
        if (!resolver) return;
        slot.listeners.delete(id);
        slot.busy = false;
        if (error) resolver.reject(error);
        else resolver.resolve(result);
        pumpQueue();
      });
      workers.push(slot);
      return slot;
    }
    return null;
  }

  function pumpQueue() {
    while (queue.length) {
      const slot = getFreeWorker();
      if (!slot) return;
      const req = queue.shift();
      dispatch(slot, req);
    }
  }

  function dispatch(slot, req) {
    slot.busy = true;
    const id = ++nextId;
    const { text, opts, timeoutMs = 100, failMode = 'open', resolve, reject } = req;
    let timer;
    const cleanup = () => {
      clearTimeout(timer);
      slot.listeners.delete(id);
    };
    slot.listeners.set(id, {
      resolve: (result) => { cleanup(); resolve(result); },
      reject: (error) => { cleanup(); reject(error); },
    });
    timer = setTimeout(() => {
      cleanup();
      slot.worker.terminate();
      const idx = workers.indexOf(slot);
      if (idx >= 0) workers.splice(idx, 1);
      if (failMode === 'closed') reject({ code: 'TIMEOUT' });
      else resolve({ findings: [], redactedText: text, scannedMs: timeoutMs, zones: null });
      pumpQueue();
    }, timeoutMs);
    slot.worker.postMessage({ id, text, opts });
  }

  function run({ text, opts = {}, timeoutMs = 100, failMode = 'open' }) {
    return new Promise((resolve, reject) => {
      const req = { text, opts, timeoutMs, failMode, resolve, reject };
      const slot = getFreeWorker();
      if (slot) dispatch(slot, req);
      else queue.push(req);
    });
  }

  function onServiceWorkerSuspend() {
    for (const slot of workers) slot.worker.terminate();
    workers.length = 0;
  }

  return { run, onServiceWorkerSuspend };
}
