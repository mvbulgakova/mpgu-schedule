import { openDB } from "idb";
import { useEffect, useState } from "react";

const DB_NAME = "mpgu-schedule-cache";
const STORE = "schedules";

async function getDb() {
  return openDB(DB_NAME, 1, {
    upgrade(db) {
      db.createObjectStore(STORE);
    },
  });
}

export function useOfflineCache<T>(key: string, liveData: T | undefined) {
  const [cached, setCached] = useState<T | null>(null);

  useEffect(() => {
    if (liveData !== undefined) {
      getDb().then((db) => db.put(STORE, liveData, key)).catch(() => {});
    }
  }, [liveData, key]);

  useEffect(() => {
    if (liveData === undefined) {
      getDb()
        .then((db) => db.get(STORE, key))
        .then((val) => { if (val) setCached(val as T); })
        .catch(() => {});
    }
  }, [key, liveData]);

  return liveData ?? cached;
}
