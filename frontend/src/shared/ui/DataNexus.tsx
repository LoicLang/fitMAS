import { useEffect, useRef } from "react";

type DataNexusProps = {
  className?: string;
};

type ParticleState = {
  x: number;
  y: number;
  z: number;
  baseX: number;
  baseY: number;
  baseZ: number;
  size: number;
  color: string;
  speed: number;
  angle: number;
};

const COLORS = ["#ff6b35", "#9d4edd", "#ffd166", "#cbd5e1"];

class Particle {
  x: number;
  y: number;
  z: number;
  baseX: number;
  baseY: number;
  baseZ: number;
  size: number;
  color: string;
  speed: number;
  angle: number;

  constructor() {
    this.angle = Math.random() * Math.PI * 2;
    const radius = Math.random() * 300 + 50;

    this.baseX = Math.cos(this.angle) * radius;
    this.baseY = Math.sin(this.angle) * radius;
    this.baseZ = Math.random() * 200 - 100;

    this.x = this.baseX;
    this.y = this.baseY;
    this.z = this.baseZ;

    this.size = Math.random() * 3 + 1;
    this.color = COLORS[Math.floor(Math.random() * COLORS.length)] || COLORS[0];
    this.speed = Math.random() * 0.002 + 0.001;
  }

  update(time: number) {
    const sin = Math.sin(this.speed * time * 0.1);
    const cos = Math.cos(this.speed * time * 0.1);

    this.x = this.baseX * cos - this.baseY * sin;
    this.y = this.baseX * sin + this.baseY * cos;

    const pulse = Math.sin(time * 0.002 + this.angle) * 10;
    this.x += Math.cos(this.angle) * pulse;
    this.y += Math.sin(this.angle) * pulse;
  }

  draw(ctx: CanvasRenderingContext2D, centerX: number, centerY: number) {
    const fov = 350;
    const scale = fov / (fov + this.z);
    const x2d = this.x * scale + centerX;
    const y2d = this.y * scale + centerY;
    const size2d = this.size * scale;

    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    ctx.lineTo(x2d, y2d);

    const gradient = ctx.createLinearGradient(centerX, centerY, x2d, y2d);
    gradient.addColorStop(0, "rgba(200, 200, 200, 0.4)");
    gradient.addColorStop(1, "rgba(200, 200, 200, 0.05)");
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 0.5 * scale;
    ctx.stroke();

    ctx.fillStyle = this.color;

    if (this.color === "#ff6b35" || this.color === "#ffd166") {
      ctx.shadowBlur = 10;
      ctx.shadowColor = this.color;
    } else {
      ctx.shadowBlur = 0;
    }

    ctx.fillRect(x2d - size2d / 2, y2d - size2d / 2, size2d, size2d);
    ctx.shadowBlur = 0;
  }
}

export function DataNexus({ className = "" }: DataNexusProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (typeof navigator !== "undefined" && navigator.userAgent.includes("jsdom")) {
      return undefined;
    }

    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    let ctx: CanvasRenderingContext2D | null = null;
    try {
      ctx = canvas.getContext("2d");
    } catch {
      return undefined;
    }

    if (!ctx) return undefined;

    let animationFrameId = 0;
    let particles: Particle[] = [];

    const init = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();

      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      particles = [];
      const numParticles = window.innerWidth < 768 ? 60 : 120;
      for (let index = 0; index < numParticles; index += 1) {
        particles.push(new Particle());
      }
    };

    const animate = (time: number) => {
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);

      const centerX = rect.width / 2;
      const centerY = rect.height / 2;

      const hubGradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, 100);
      hubGradient.addColorStop(0, "rgba(255, 107, 53, 0.15)");
      hubGradient.addColorStop(1, "rgba(255, 107, 53, 0)");
      ctx.fillStyle = hubGradient;
      ctx.beginPath();
      ctx.arc(centerX, centerY, 100, 0, Math.PI * 2);
      ctx.fill();

      particles.forEach((particle) => {
        particle.update(time);
        particle.draw(ctx, centerX, centerY);
      });

      animationFrameId = window.requestAnimationFrame(animate);
    };

    const timeoutId = window.setTimeout(() => {
      init();
      animate(0);
    }, 0);

    const handleResize = () => {
      init();
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener("resize", handleResize);
      window.cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return <canvas ref={canvasRef} className={`block h-full w-full ${className}`} style={{ touchAction: "none" }} />;
}
