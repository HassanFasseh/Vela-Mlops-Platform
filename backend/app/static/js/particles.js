/*
 * Vela background particle network — a very low-opacity constellation
 * behind the app shell's content area, echoing the landing page's
 * "sailing through open water" theme without competing with content.
 *
 * Mounted by shell.js at the end of Shell.mount(), never before — mount()
 * does document.body.innerHTML = "" as one of its first steps, which
 * would destroy a canvas mounted any earlier.
 *
 * The canvas draws its own solid navy fill each frame plus the particle
 * dots/links, then sits as the first child of <body>, behind everything.
 * .shell-sidebar and .shell-topbar have their own opaque backgrounds and
 * simply paint over it in their footprint (normal DOM/paint order — no
 * z-index tricks needed there); .shell-main has no background of its own,
 * so the canvas shows through as its backdrop. Pointer-events are off, so
 * it can never intercept a click meant for real UI.
 */

const Particles = (() => {
  const BG_FILL = "#020818";
  const PARTICLE_COUNT = 55;
  const MAX_LINK_DIST = 130;
  const SPEED = 0.05; // px/frame — deliberately slow, this is a backdrop, not a feature
  const LINK_ALPHA_MAX = 0.05; // "very low opacity, ~5%"
  const NODE_ALPHA_MAX = 0.09;

  function prefersReducedMotion() {
    try {
      return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) {
      return false;
    }
  }

  function mount() {
    if (document.getElementById("vela-particles")) return; // already mounted this page load

    const canvas = document.createElement("canvas");
    canvas.id = "vela-particles";
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.position = "fixed";
    canvas.style.inset = "0";
    canvas.style.width = "100vw";
    canvas.style.height = "100vh";
    canvas.style.zIndex = "0";
    canvas.style.pointerEvents = "none";
    canvas.style.display = "block";
    document.body.insertBefore(canvas, document.body.firstChild);

    const ctx = canvas.getContext("2d");
    if (!ctx) return; // no canvas support — the plain CSS background token still applies

    const reduceMotion = prefersReducedMotion();
    let width = 0;
    let height = 0;
    let particles = [];
    let dpr = Math.min(window.devicePixelRatio || 1, 2);

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function seed() {
      particles = Array.from({ length: PARTICLE_COUNT }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * SPEED,
        vy: (Math.random() - 0.5) * SPEED,
        r: 1 + Math.random() * 1.4,
        phase: Math.random() * Math.PI * 2,
      }));
    }

    function drawFrame(t) {
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = BG_FILL;
      ctx.fillRect(0, 0, width, height);

      if (!reduceMotion) {
        particles.forEach((p) => {
          p.x += p.vx;
          p.y += p.vy;
          if (p.x < 0 || p.x > width) p.vx *= -1;
          if (p.y < 0 || p.y > height) p.vy *= -1;
        });
      }

      ctx.lineWidth = 1;
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const a = particles[i];
          const b = particles[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < MAX_LINK_DIST) {
            const alpha = (1 - dist / MAX_LINK_DIST) * LINK_ALPHA_MAX;
            ctx.strokeStyle = "rgba(126,184,247," + alpha.toFixed(3) + ")";
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }

      particles.forEach((p) => {
        const pulse = reduceMotion ? 1 : 0.55 + 0.45 * Math.sin((t || 0) / 1400 + p.phase);
        ctx.fillStyle = "rgba(56,189,248," + (NODE_ALPHA_MAX * pulse).toFixed(3) + ")";
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    function loop(t) {
      drawFrame(t);
      raf = requestAnimationFrame(loop);
    }

    let raf = null;
    resize();
    seed();

    if (reduceMotion) {
      // One static frame — same constellation texture, no motion at all.
      drawFrame(0);
    } else {
      raf = requestAnimationFrame(loop);
    }

    window.addEventListener("resize", () => {
      resize();
      // Re-seed on resize rather than let particles drift back in from
      // outside the new bounds — instant and avoids a lingering empty
      // corner after a big viewport shrink.
      seed();
      if (reduceMotion) drawFrame(0);
    });
  }

  return { mount };
})();
