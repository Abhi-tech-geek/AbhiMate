# 🚀 AbhiMate – AI Testing Platform (Multi-Agent System)

## 🧠 Overview

AbhiMate is an AI-powered multi-agent QA testing platform that automates the entire testing lifecycle — from test case generation to execution, bug analysis, and reporting.

This project combines **Generative AI + Selenium Automation + Multi-Agent Systems** to simulate a real-world intelligent QA pipeline.

---

## ⚡ Features

### 🤖 AI Test Case Generator

* Generates structured test cases using LLM (Groq - LLaMA3)
* Covers:

  * Positive scenarios
  * Negative scenarios
  * Edge cases

### ⚙️ Automation Engine (Selenium)

* Executes test cases using Selenium WebDriver
* Automates:

  * Browser navigation
  * Form interactions
  * Click actions

### 🐞 Bug Analyzer

* Uses AI to analyze failed test cases
* Provides human-readable explanations for failures

### 📊 Dashboard

* Interactive UI using Streamlit
* Displays:

  * Pass/Fail metrics
  * Charts & insights

### 🧩 Multi-Agent Architecture

* Agent-based system:

  * Test Generator Agent
  * Execution Agent
  * Bug Analyzer Agent
  * Reporting Agent

---

## 🏗️ Architecture

Input → Test Generator → Execution → Bug Analyzer → Reporting → Dashboard

---

## 🛠️ Tech Stack

* **Python**
* **Groq API (LLaMA3)**
* **Selenium WebDriver**
* **Streamlit**
* **Pandas / Matplotlib**
* **dotenv**

---

## 📁 Project Structure

```id="r1m9xk"
ai-testing-platform/
│
├── agents/
│   ├── test_generator_agent.py
│   ├── execution_agent.py
│   ├── bug_analyzer_agent.py
│   └── reporting_agent.py
│
├── services/
├── prompt_templates/
├── output/
├── dashboard.py
├── main.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## ⚙️ Installation

```bash id="kj4r8x"
git clone https://github.com/Abhi-tech-geek/AbhiMate.git
cd AbhiMate
pip install -r requirements.txt
```

---

## 🔐 Setup Environment Variables

Create a `.env` file:

```id="9p3xqa"
GROQ_API_KEY=your_api_key_here
```

---

## ▶️ Run the Project

### 1️⃣ Run AI Testing Pipeline

```bash id="w0l7yb"
python main.py
```

### 2️⃣ Launch Dashboard

```bash id="t8f2nv"
streamlit run dashboard.py
```

---

## 📊 Sample Output

* `output/test_cases.json`
* `output/execution_results.json`
* `output/final_report.json`

---

## 📸 Screenshots (Add your images here)

* Dashboard UI
* Selenium test execution
* Bug analysis output

---

## 🚀 Future Improvements

* Self-healing selectors (AI-based)
* API testing integration
* CI/CD pipeline integration
* Cloud deployment
* Advanced AI insights

---

## 💼 Use Case

This project demonstrates how AI can transform traditional QA processes into intelligent, automated systems using Selenium-based execution and LLM-driven insights.

---

## 👨‍💻 Author

**Abhinav (AbhiMate Creator)**
AI + QA Automation Enthusiast 🚀

---

## ⭐ Contribute / Support

If you like this project:

* ⭐ Star the repo
* 🍴 Fork it
* 💡 Share feedback

---
