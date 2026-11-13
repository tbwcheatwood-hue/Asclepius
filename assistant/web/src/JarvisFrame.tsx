import { memo } from "react";

/** Stable iframe — parent re-renders must not change `src` or remount JARVIS. */
export const JarvisFrame = memo(function JarvisFrame({ baseUrl }: { baseUrl: string }) {
  const root = `${baseUrl.replace(/\/$/, "")}/`;
  return (
    <iframe
      title="J.A.R.V.I.S. personal assistant"
      className="jarvis-frame"
      src={root}
      allow="microphone; clipboard-write"
    />
  );
});
