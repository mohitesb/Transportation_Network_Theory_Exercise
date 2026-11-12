# Setup: from a fresh computer to a running lab

This guide starts from nothing installed. It takes about 10–15 minutes, most of it waiting for downloads. You need an internet connection and about 1.5 GB of free disk space.

You only do steps 1–4 once. After that, use **Run the lab again** at the bottom.

---

## 1. Install Python (3.11 or 3.12)

Use **Python 3.11 or 3.12**. Newer versions sometimes don't have the geospatial libraries ready yet.

First check whether you already have it. Open a terminal:

- **Windows:** press the Start key, type `PowerShell`, and open it.
- **macOS:** press Cmd + Space, type `Terminal`, and open it.
- **Linux:** open your terminal app.

Then type:

```bash
python --version
```

On macOS or Linux, also try `python3 --version`. If you see `Python 3.11.x` or `Python 3.12.x`, skip to step 2.

### Windows

1. Go to https://www.python.org/downloads/windows/ and download the **Python 3.12** "Windows installer (64-bit)".
2. Run it. On the first screen, **check "Add python.exe to PATH"**, then click **Install Now**.
3. Close PowerShell, open a new one, and run `python --version` to confirm.

If `python` opens the Microsoft Store, go to Settings → Apps → Advanced app settings → App execution aliases, and turn off the two "python" entries. Then open a new PowerShell.

### macOS

1. Go to https://www.python.org/downloads/macos/ and download the **Python 3.12** macOS 64-bit universal installer.
2. Run the `.pkg` and click through.
3. Open a new Terminal and run `python3 --version`.

On a Mac, type `python3` wherever this guide says `python`.

### Linux (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
python3 --version
```

On Linux, type `python3` wherever this guide says `python`.

---

## 2. Get the lab files

**Option A: with Git (recommended, makes updates easy)**

Install Git if you don't have it:

- Windows: https://git-scm.com/download/win (accept the defaults)
- macOS: run `git --version` in Terminal and accept the prompt to install the developer tools
- Linux: installed in step 1

Then:

```bash
git clone https://github.com/<your-github-username>/Network_Theory_Exercise.git
cd Network_Theory_Exercise
```

**Option B: without Git**

On the GitHub page, click **Code → Download ZIP**, unzip it, then in the terminal go into the folder:

```bash
cd path/to/Network_Theory_Exercise
```

(Tip: type `cd ` with a space, then drag the folder onto the terminal window and press Enter.)

---

## 3. Create a virtual environment

A virtual environment keeps the lab's libraries separate from anything else on your computer. Run this inside the `Network_Theory_Exercise` folder.

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell says running scripts is disabled, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

When it works, your prompt starts with `(.venv)`. Run every command after this in that same window.

---

## 4. Install the libraries

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This installs OSMnx, NetworkX, igraph, GeoPandas, Shapely, pyproj, pyogrio, Matplotlib, Plotly, Streamlit, pandas, NumPy, and SciPy. It takes a few minutes.

Check that everything works:

```bash
python scripts/check_lab.py
```

It should print a few lines ending in `ok` and no errors.

---

## 5. Start the lab

```bash
python -m streamlit run app.py
```

Your browser should open http://localhost:8501. If it doesn't, copy the address from the terminal into your browser.

To stop the lab, click the terminal and press **Ctrl + C**.

---

## Run the lab again (every time after the first)

Open a terminal, go into the folder, activate the environment, and start the lab:

**Windows**

```powershell
cd path\to\Network_Theory_Exercise
.venv\Scripts\Activate.ps1
python -m streamlit run app.py
```

Or double-click `scripts\start_lab.bat`.

**macOS / Linux**

```bash
cd path/to/Network_Theory_Exercise
source .venv/bin/activate
python -m streamlit run app.py
```

Or run `bash scripts/start_lab.sh`.

To get the latest version (if you used Git): `git pull`, then `python -m pip install -r requirements.txt`.

---

## For the instructor: one computer, whole class

You can run the lab on one machine and have students open it in their browsers, so they don't need to install anything.

```bash
python -m streamlit run app.py --server.address 0.0.0.0
```

Streamlit prints a **Network URL** such as `http://192.168.1.25:8501`. Students on the same network open that address. Campus Wi-Fi sometimes blocks device-to-device traffic. If students can't connect, use a wired lab network or have them install locally.

To avoid thirty identical OpenStreetMap requests, download the place once, click **Download this network (GraphML)**, and give that file to the class to upload.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `python` or `pip` not found | On Windows, reinstall Python with "Add python.exe to PATH" checked. On macOS/Linux, use `python3`. |
| `No module named streamlit` (or osmnx, etc.) | The environment isn't active. Run the activate command from step 3, then retry. |
| Install fails building `igraph`, `shapely`, `pyproj`, or `pyogrio` | You are probably on a too-new Python. Install Python 3.12, delete the `.venv` folder, and repeat steps 3–4. |
| Port 8501 already in use | Another lab is still running. Close it, or run `python -m streamlit run app.py --server.port 8502`. |
| OSMnx download times out | OpenStreetMap servers are busy. Use **Load a file from OpenStreetMap** in the app (see the Student Guide), or a smaller place. |
| Browser shows a blank page | Refresh. If it persists, stop with Ctrl + C and start again. |

### Fallback: Conda / Miniforge

If pip installs keep failing (most often on older Windows machines), install Miniforge from https://github.com/conda-forge/miniforge, open "Miniforge Prompt", and run:

```bash
conda create -n netlab -c conda-forge python=3.12 osmnx python-igraph streamlit plotly scipy
conda activate netlab
cd path/to/Network_Theory_Exercise
python scripts/check_lab.py
python -m streamlit run app.py
```

Next time, run `conda activate netlab` instead of the `.venv` activate command.
