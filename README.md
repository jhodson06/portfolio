# Joshua Hodson | Engineering Portfolio

This repository contains the source code for my personal engineering and software portfolio website. The site is a fully static, highly optimized web application showcasing projects across robotics, software engineering, machine learning, and algorithmic trading.

## 🚀 Features

- **Live Trading Bot Widget:** A live-updating widget powered by Chart.js that fetches real-time equity and PnL data from an autonomous intraday Python trading bot.
- **Dynamic Backgrounds:** Custom HTML Canvas background animations featuring a swirling flow-field (vector) in light mode and digital rainfall in dark mode.
- **Dark/Light Mode:** A fully responsive, user-toggleable theme system.
- **Zero-Dependency Core:** Built using vanilla HTML5, CSS3, and JavaScript to guarantee maximum performance and zero bloat.
- **Asset Pipeline:** Images and code snippets are strictly organized, with raw Python trading algorithms sanitized for public viewing without exposing proprietary logic.

## 📁 Projects Featured

- **Algorithmic Trading Bot:** An autonomous, cloud-hosted Python bot trading intraday momentum strategies.
- **Local AI Workspace:** A privacy-first, locally orchestrated AI dev environment utilizing open-source models.
- **Hexapod Robot:** A custom-designed 18-DOF hexapod featuring IK-driven locomotion and Bluetooth control.
- **Playing Card Dealer:** A first-year mechatronics design project focused on complex physical mechanism design.
- **VEX Robotics:** A competition robot built for the 2023 VEX season.
- **Additional Highlights:** CNC machining, structural failure analysis, and rapid prototyping work.

## 🛠️ Architecture

- `index.html` - The main landing page featuring project cards and the live trading widget.
- `styles.css` - A comprehensive custom design system with CSS Grid/Flexbox layouts and CSS Variables for dynamic theming.
- `main.js` - Contains the theme toggling logic, Chart.js data fetching/rendering, and the HTML Canvas background engine.
- `assets/` - Contains all imagery, sanitized code samples (like `live_trader.py`), and documentation used across the site.
- `portfolio.json` - The live data endpoint feeding the trading bot widget.

## 💻 Running Locally

To view the portfolio locally, simply clone the repository and run a local web server:

```bash
git clone https://github.com/jhodson06/portfolio.git
cd portfolio
python -m http.server 8000
```

Navigate to `http://localhost:8000` in your browser.

## 📬 Contact

- **Email:** jhodson@uwaterloo.ca
- **LinkedIn:** [jhodson](https://www.linkedin.com/in/jhodson/)
