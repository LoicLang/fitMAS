import { buildSvgPath, decodePolyline } from "../../lib/polyline";

export function RoutePreview({ polyline }: { polyline?: string | null }) {
  const path = buildSvgPath(decodePolyline(polyline));

  return (
    <div className="relative overflow-hidden rounded-[2rem] border border-black/6 bg-zinc-50">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_30%,rgba(255,107,53,0.12),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.4),transparent_35%)]" />
      <div className="absolute inset-0 opacity-30 [background-image:linear-gradient(135deg,rgba(0,0,0,0.05)_2px,transparent_2px),linear-gradient(45deg,rgba(0,0,0,0.03)_2px,transparent_2px)] [background-size:2.4rem_2.4rem]" />
      {path ? (
        <svg viewBox="0 0 100 48" preserveAspectRatio="none" className="relative h-44 w-full">
          <path d={path} className="fill-none stroke-[rgba(255,107,53,0.2)] stroke-[4]" />
          <path d={path} className="fill-none stroke-[var(--accent)] stroke-[2.4] [filter:drop-shadow(0_0_14px_rgba(255,107,53,0.28))]" />
        </svg>
      ) : (
        <div className="h-44 w-full" />
      )}
      <div className="absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-white to-transparent" />
    </div>
  );
}
