# AbhiMate - AI Testing Platform (Multi-Agent)

AbhiMate is a state-of-the-art **Multi-Agent QA System** designed to automate the entire software testing lifecycle. It natively bridges AI-driven test case generation with persistent browser execution, bug diagnosis, and executive reporting. 

## 🚀 Features
- **Test Case Generator (Agent 1):** Uses Llama-3 70B (via Groq API) to ingest human descriptions of a feature and extrapolate meticulously detailed, line-by-line test cases (Positive, Negative, Edge).
- **Execution Engine (Agent 2):** Parses the AI-generated Selenium scripts and spins up a local Chromium browser asynchronously to autonomously validate the web application.
- **Bug Analyzer (Agent 3):** Any failing Selenium tests are captured, dumped with their stack traces into the LLM, and diagnosed natively like a Senior QA engineer.
- **Reporting Agent (Agent 4):** Compiles the metrics into an executive summary board.
- **Premium Dashboard Interface:** Built with Flask and stylized with modern glassmorphism. It features "Two-Step Authentication" where tests are generated explicitly for review *before* browser execution, wrapped in a robust Session framework.

## 🛠️ Tech Stack
- **Backend**: Python 3, Flask
- **AI/LLM**: Groq API (Llama 3.3 70B Versatile)
- **Automation**: Selenium WebDriver & WebDriver Manager
- **Frontend**: HTML5, Vanilla CSS (Glassmorphic), JavaScript Fetch API

## 📦 Installation Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/ai-testing-platform.git
   cd ai-testing-platform
   ```

2. **Set up a Virtual Environment**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Mac/Linux:
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration**
   - Copy the `.env.example` file and rename it to `.env`.
   - Insert your authentic Groq API Key:
     ```env
     GROQ_API_KEY=your_actual_key_here
     ```

## 🎯 How to Run
Trigger the fully interactive web dashboard by running the Flask server:
```bash
python app.py
```
Then navigate to `http://127.0.0.1:5000` via your web browser. 
- Create a **New Chat**.
- Describe the feature you want to test (e.g., "Google Search form").
- Let AbhiMate construct exhaustive test cases.
- Select the **Execute Selenium Automation** button to run them natively!

## 📸 Screenshots
*(Coming Soon)*
- Add screenshots of the dark-mode dashboard here.
- Add screenshots of the Session Sidebar here.

## 🔮 Future Improvements
- Migration to asynchronous remote Selenium grids or Playwright grids.
- Dockerizing the workspace to containerize test isolation.
- Automatic integration with CI/CD platforms (GitHub Actions, Jenkins).
