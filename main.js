const navToggle = document.querySelector(".nav-toggle");
const siteNav = document.querySelector(".site-nav");
const themeToggle = document.querySelector(".theme-toggle");
const root = document.documentElement;
const savedTheme = localStorage.getItem("portfolio-theme") || "dark";

function setTheme(theme) {
  root.dataset.theme = theme;

  if (!themeToggle) {
    return;
  }

  const isDark = theme === "dark";
  themeToggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
  themeToggle.innerHTML = `<i data-lucide="${isDark ? "sun" : "moon"}"></i>`;

  if (window.lucide) {
    window.lucide.createIcons();
  }

  if (window.portfolioChart) {
    const gridColor = isDark ? "rgba(255, 255, 255, 0.05)" : "rgba(0, 0, 0, 0.05)";
    const textColor = isDark ? "rgba(255, 255, 255, 0.5)" : "rgba(0, 0, 0, 0.5)";
    const accentColor = getComputedStyle(root).getPropertyValue("--accent").trim() || "#22c55e";

    window.portfolioChart.data.datasets[0].borderColor = accentColor;
    window.portfolioChart.data.datasets[0].pointBackgroundColor = accentColor;
    window.portfolioChart.options.scales.x.ticks.color = textColor;
    window.portfolioChart.options.scales.y.grid.color = gridColor;
    window.portfolioChart.options.scales.y.ticks.color = textColor;
    window.portfolioChart.update();
  }
}

// Canvas Background Animation (Digital Rain / Tech Lines)
const bgCanvas = document.getElementById("bg-canvas");
if (bgCanvas) {
  const ctx = bgCanvas.getContext("2d");
  let width, height;


  function resize() {
    width = window.innerWidth;
    height = window.innerHeight;
    bgCanvas.width = width;
    bgCanvas.height = height;
  }
  
  window.addEventListener("resize", resize);
  resize();

  let techLines = [];

  class TechLine {
    constructor() {
      this.reset(true);
    }

    reset(initial = false) {
      this.x = Math.random() * width;
      this.y = initial ? Math.random() * height : -100;
      this.length = Math.random() * 80 + 60;
      this.speed = Math.random() * 2.0 + 0.5;
      this.thickness = Math.random() * 1.25 + 0.75;
      this.opacity = Math.random() * 0.35 + 0.30;
      
      const colors = ['var(--accent)', 'var(--steel)'];
      this.cssColor = colors[Math.floor(Math.random() * colors.length)];
      this.colorCache = getComputedStyle(document.documentElement).getPropertyValue(this.cssColor.replace('var(', '').replace(')', '')).trim() || '#ffffff';
    }

    draw() {
      const colorVal = this.colorCache || '#ffffff';
      
      this.y += this.speed;
      if (this.y - this.length > height) {
        this.reset();
      }

      const grad = ctx.createLinearGradient(this.x, this.y - this.length, this.x, this.y);
      grad.addColorStop(0, 'rgba(0,0,0,0)');
      
      ctx.globalAlpha = this.opacity;
      grad.addColorStop(1, colorVal);
      
      ctx.beginPath();
      ctx.strokeStyle = grad;
      ctx.lineWidth = this.thickness;
      ctx.moveTo(this.x, this.y - this.length);
      ctx.lineTo(this.x, this.y);
      ctx.stroke();
      ctx.globalAlpha = 1.0;
    }
  }

  const techLineCount = window.innerWidth < 768 ? 30 : 80;
  for (let i = 0; i < techLineCount; i++) {
    techLines.push(new TechLine());
  }

  let flowTime = 0;
  let flowColors = [];
  let flowLines = [];

  function getFlowAngle(x, y, t) {
    const scale = 0.002;
    const a1 = Math.sin(x * scale + t) * Math.cos(y * scale + t);
    const a2 = Math.sin(y * scale * 1.5 - t * 0.5) * Math.cos(x * scale * 1.5 + t * 0.5);
    return (a1 + a2) * Math.PI;
  }

  class FlowLine {
    constructor() {
      this.reset();
    }
    reset() {
      this.x = Math.random() * width;
      this.y = Math.random() * height;
      this.history = [];
      this.historyMax = Math.floor(Math.random() * 30 + 15);
      this.speed = Math.random() * 1.0 + 0.5;
      this.life = 0;
      this.maxLife = Math.random() * 200 + 100;
      
      if (flowColors.length === 0) {
        flowColors = [
          getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#146c5c',
          getComputedStyle(document.documentElement).getPropertyValue('--steel').trim() || '#31526b',
          getComputedStyle(document.documentElement).getPropertyValue('--accent-dark').trim() || '#0e4a3f'
        ];
      }
      this.color = flowColors[Math.floor(Math.random() * flowColors.length)];
    }
    draw(t) {
      this.history.push({x: this.x, y: this.y});
      if (this.history.length > this.historyMax) {
        this.history.shift();
      }
      
      const angle = getFlowAngle(this.x, this.y, t);
      this.x += Math.cos(angle) * this.speed;
      this.y += Math.sin(angle) * this.speed;
      
      if (this.history.length > 1) {
        ctx.beginPath();
        ctx.moveTo(this.history[0].x, this.history[0].y);
        for (let i = 1; i < this.history.length; i++) {
          ctx.lineTo(this.history[i].x, this.history[i].y);
        }
        
        const fade = Math.sin((this.life / this.maxLife) * Math.PI);
        ctx.globalAlpha = fade * 0.85;
        ctx.strokeStyle = this.color;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      
      this.life++;
      if (this.life >= this.maxLife || this.x < 0 || this.x > width || this.y < 0 || this.y > height) {
        this.reset();
      }
    }
  }

  const flowLineCount = window.innerWidth < 768 ? 60 : 180;
  for (let i = 0; i < flowLineCount; i++) {
    flowLines.push(new FlowLine());
  }

  function drawFlowField() {
    flowTime += 0.003;
    flowLines.forEach(line => line.draw(flowTime));
  }

  function animate() {
    ctx.clearRect(0, 0, width, height);
    
    if (document.documentElement.dataset.theme === "light") {
      drawFlowField();
    } else {
      techLines.forEach(line => line.draw());
    }
    
    requestAnimationFrame(animate);
  }
  
  // Defer animation until after initial page load and paint to improve PageSpeed
  window.addEventListener('load', () => {
    setTimeout(() => {
      requestAnimationFrame(animate);
    }, 100);
  });
}

setTheme(savedTheme);

if (navToggle && siteNav) {
  navToggle.addEventListener("click", () => {
    const isOpen = siteNav.classList.toggle("is-open");
    navToggle.setAttribute("aria-expanded", String(isOpen));
  });

  siteNav.addEventListener("click", (event) => {
    if (event.target instanceof HTMLAnchorElement) {
      siteNav.classList.remove("is-open");
      navToggle.setAttribute("aria-expanded", "false");
    }
  });
}

if (themeToggle) {
  themeToggle.addEventListener("click", () => {
    const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("portfolio-theme", nextTheme);
    setTheme(nextTheme);
  });
}

window.addEventListener("load", () => {
  if (window.lucide) {
    window.lucide.createIcons();
    setTheme(root.dataset.theme || savedTheme);
  }
});

// Portfolio Widget Logic
const portfolioWidget = document.getElementById("portfolio-widget");
if (portfolioWidget) {
  fetch("portfolio.json")
    .then(res => {
      if (!res.ok) throw new Error("Failed to fetch");
      return res.json();
    })
    .then(data => {
      const equityFormatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
      const currentEquity = parseFloat(data.equity);
      const lastEquity = parseFloat(data.last_equity);
      
      const change = currentEquity - lastEquity;
      const changePct = (change / lastEquity) * 100;
      
      const isPositive = change >= 0;
      const color = isPositive ? "var(--accent)" : "#f85149";
      const sign = isPositive ? "+" : "";

      document.getElementById("portfolio-equity").innerText = equityFormatter.format(currentEquity);
      
      const plElement = document.getElementById("portfolio-pl");
      plElement.innerText = `${sign}${equityFormatter.format(change)} (${sign}${changePct.toFixed(2)}%) Today`;
      plElement.style.color = color;

      if (data.last_updated) {
        const date = new Date(data.last_updated);
        const timestampElement = document.getElementById("portfolio-timestamp");
        if (timestampElement) {
          timestampElement.innerText = `Last updated: ${date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
        }
      }

      portfolioWidget.style.display = "flex";

      // Chart.js rendering
      const canvas = document.getElementById("portfolio-chart");
      if (canvas && window.Chart && data.history && data.history.length > 0) {
        const ctx = canvas.getContext("2d");
        const isDark = root.dataset.theme === "dark" || (!root.dataset.theme && savedTheme === "dark");
        const gridColor = isDark ? "rgba(255, 255, 255, 0.05)" : "rgba(0, 0, 0, 0.05)";
        const textColor = isDark ? "rgba(255, 255, 255, 0.5)" : "rgba(0, 0, 0, 0.5)";
        
        // Use computed value for accent color
        const accentColor = getComputedStyle(root).getPropertyValue("--accent").trim() || "#22c55e";

        const labels = data.history.map(point => {
          const date = new Date(point.timestamp * 1000);
          return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        });
        const chartData = data.history.map(point => point.equity);

        window.portfolioChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [{
              label: 'Equity',
              data: chartData,
              borderColor: accentColor,
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 4,
              pointBackgroundColor: accentColor,
              fill: false,
              tension: 0.1
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
              intersect: false,
              mode: 'index',
            },
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label: (context) => equityFormatter.format(context.parsed.y)
                }
              }
            },
            scales: {
              x: {
                grid: { display: false, drawBorder: false },
                ticks: {
                  color: textColor,
                  maxRotation: 0,
                  maxTicksLimit: 5
                }
              },
              y: {
                grid: { color: gridColor, drawBorder: false },
                ticks: {
                  color: textColor,
                  callback: (value) => '$' + (value / 1000) + 'k'
                }
              }
            }
          }
        });
      } else if (canvas) {
        // If history is empty, hide the canvas container
        canvas.parentElement.style.display = "none";
      }
    })
    .catch(err => {
      console.error("Portfolio widget error:", err);
    });
}
