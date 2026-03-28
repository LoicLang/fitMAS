import { motion } from "motion/react";
import { DataNexus } from "./DataNexus";

export function AmbientBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[var(--app-bg)]" />
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#00000005_1px,transparent_1px),linear-gradient(to_bottom,#00000005_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_80%_80%_at_50%_50%,#000_10%,transparent_100%)]" />
      <div className="absolute inset-0 [mask-image:linear-gradient(to_bottom,black_0%,black_38%,transparent_78%)]">
        <DataNexus className="opacity-80" />
      </div>
      <motion.div
        animate={{ scale: [1, 1.1, 1], opacity: [0.1, 0.2, 0.1] }}
        transition={{ duration: 15, repeat: Infinity, ease: "easeInOut" }}
        className="absolute -right-1/4 -top-1/4 h-[50vw] w-[50vw] rounded-full bg-[#ff6b35] blur-[120px] mix-blend-multiply"
      />
      <motion.div
        animate={{ scale: [1, 1.2, 1], opacity: [0.05, 0.1, 0.05] }}
        transition={{ duration: 20, repeat: Infinity, ease: "easeInOut", delay: 2 }}
        className="absolute -left-1/4 bottom-0 h-[60vw] w-[60vw] rounded-full bg-[#ffd166] blur-[150px] mix-blend-multiply"
      />
      <div className="absolute inset-0 bg-[linear-gradient(to_bottom,rgba(248,249,250,0.08)_0%,rgba(248,249,250,0.28)_24%,rgba(248,249,250,0.72)_54%,rgba(248,249,250,0.94)_100%)]" />
    </div>
  );
}
