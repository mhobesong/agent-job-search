const themeToggle = document.getElementById('theme-toggle');
const skillsInput = document.getElementById('skills');
const skillsChipsContainer = document.getElementById('skills-chips');
const searchForm = document.getElementById('search-form');
const dropZone = document.getElementById('drop-zone');
const resumeFileInput = document.getElementById('resume-file');
const fileInfo = document.getElementById('file-info');
const previewBtn = document.getElementById('preview-query');
const startBtn = document.getElementById('start-search');
const progressSection = document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');
const progressBar = document.getElementById('progress-bar');
const phaseLabel = document.getElementById('phase-label');
const currentTask = document.getElementById('current-task');
const eventLog = document.getElementById('event-log');
const captchaBanner = document.getElementById('captcha-banner');
const captchaMsg = document.getElementById('captcha-msg');
const resultsTableBody = document.querySelector('#results-table tbody');
const resultsSummary = document.querySelector('.results-summary');
const downloadBtn = document.getElementById('download-json');
const copyUrlsBtn = document.getElementById('copy-urls');

let skills = [];
let eventSource = null;

// --- Theme Management ---
const savedTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
document.documentElement.setAttribute('data:theme', savedTheme); // Initial attempt, but better to use data-theme on body or root
document.body.setAttribute('data-theme', savedTheme);

themeToggle.addEventListener('click', () => {
    const currentTheme = document.body.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.body.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    themeToggle.querySelector('.icon').textContent = newTheme === 'dark' ? '☀️' : '🌙';
});

// --- Skills Chip Logic ---
skillsInput.addEventListener('input', (e) => {
    const val = e.target.value;
    skills = val.split(',').map(s => s.trim()).filter(s => s !== '');
    renderChips();
});

function renderChips() {
    skillsChipsContainer.innerHTML = '';
    skills.forEach(skill => {
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.innerHTML = `${skill} <span class="remove-chip" data-skill="${skill}">&times;</span>`;
    skillsChipsContainer.appendChild(chip);
    });
}

skillsChipsContainer.addEventListener('click', (e) => {
    if (e.target.classList.contains('remove-chip')) {
    const skillToRemove = e.target.dataset.skill;
    skills = skills.filter(s => s !== skillToRemove);
    skillsInput.value = skills.join(', ');
    renderChips();
    }
});

// --- File Upload Logic ---
['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, preventDefaults, false);
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
});

dropZone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    handleFiles(files);
});

resumeFileInput.addEventListener('change', (e) => {
    handleFiles(e.target.files);
});

function handleFiles(files) {
    if (files.length > 0) {
    const file = files[0];
    fileInfo.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    fileInfo.classList.remove('hidden');
    resumeFileInput.files = files;
    }
}

// --- API Interaction ---
previewBtn.addEventListener('click', async () => {
    const skillsVal = skillsInput.value;
    const remote = document.getElementById('remote-toggle').checked ? 1 : 0;
    try {
    const response = await fetch(`/api/query?skills=${encodeURIComponent(skillsVal)}&remote=${remote}`);
    const query = await response.text();
    alert(`Generated Query: ${query}`);
    } catch (err) {
    console.error(err);
    }
});

searchForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(searchForm);
    const runId = await startRun(formData);
    if (runId) {
    startStreaming(runId);
    }
});

async function startRun(formData) {
    try {
    const response = await fetch('/api/run', {
        method: 'POST',
        body: formData
    });
    if (response.status === 409) {
        alert('A search is already in progress.');
        return null;
    }
    if (!response.ok) {
        const err = await response.json();
        alert(`Error: ${err.detail || 'Failed to start run'}`);
        return null;
    }
    const data = await response.json();
    return data.run_id;
    } catch (err) {
    alert('Failed to connect to server.');
    return null;
    }
}

function startStreaming(runId) {
    progressSection.classList.remove('hidden');
    resultsSection.classList.add('hidden');
    eventLog.innerHTML = '';
    progressBar.style.width = '0%';
    progressBar.classList.remove('error', 'success');
    phaseLabel.textContent = 'Starting...';
    currentTask.textContent = '';
    captchaBanner.classList.add('hidden');

    eventSource = new EventSource(`/api/stream/${runId}`);

    eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleEvent(data);
    };

    eventSource.onerror = () => {
        console.error('SSE connection lost.');
        eventLog.innerHTML += `<div>[SYSTEM] Connection lost... attempting to reconnect</div>`;
        // The browser's EventSource will automatically try to reconnect.
        // We can poll /api/status here if needed.
    };
    
    // Add a listener for the 'finish' or 'error' events specifically if they are separate
    // but usually they are part of the JSON stream.
    };
}

function handleEvent(data) {
    const { type, payload } = data;

    switch (type) {
    case 'phase':
    case 'listing_page':
    case 'candidates_total':
    case 'candidate_start':
        phaseLabel.textContent = data.payload.phase || 'Evaluating candidates...';
        if (data.type === 'listing_page') {
            phaseLabel.textContent = `Collecting Google results — page ${data.payload.page}/${data.payload.total}`;
        }
        if (data.type === 'candidates_total') {
            // We can't know total candidates until they are all found, 
            // but we know how many we scale between.
        }
        break;
    case 'candidate_start':
        currentTask.textContent = `Checking [${data.payload.idx}/${data.payload.total}] ${data.payload.url}`;
        progressBar.style.width = `${(data.payload.idx / data.payload.total) * 100}%`;
        break;
    case 'candidate_step':
        const stepDiv = document.createElement('div');
        stepDiv.textContent = `[${data.payload.stage.toUpperCase()}] ${data.payload.ok ? 'OK' : 'FAILED'} - ${data.payload.detail || ''}`;
        eventLog.prepend(stepDiv);
        break;
    case 'candidate_result':
        const row = data.payload;
        const tr = document.createElement('tr');
        const scoreClass = getScoreClass(row.fit_score);
        tr.innerHTML = `
            <td>${resultsTableBody.children.length + 1}</td>
            <td><a href="${row.url}" target="_blank">${row.url.substring(0, 40)}...</a></td>
            <td>${row.skills_matched.join(', ')}</td>
            <td>${row.remote_found ? '✓' : '✗'}</td>
            <td><span class="badge ${scoreClass}">${row.fit_score}</span></td>
            <td><span class="badge badge-gray">${row.status}</span></td>
        `;
        resultsTableBody.appendChild(tr);
        break;
    case 'captcha':
        captchaBanner.classList.remove('hidden');
        captchaMsg.textContent = `Solve the captcha in the browser window — ${data.payload.state}`;
        if (data.payload.state === 'solved') {
            setTimeout(() => captchaBanner.classList.add('hidden'), 5000);
        }
        break;
    case 'warning':
        const warnDiv = document.createElement('div');
        warnDiv.style.color = 'varvar(--warning-color)';
        warnDiv.textContent = `[WARN] ${data.payload.msg}`;
        eventLog.prepend(warnDiv);
        break;
    case 'finish':
        progressBar.classList.add('success');
        finishRun(data.payload);
        break;
    case 'error':
        progressBar.classList.add('error');
        alert(`Error: ${data.payload.msg}`);
        finishRun(null);
        break;
    }
}

function getScoreClass(score) {
    if (score >= 80) return 'badge-green';
    if (score >= 60) return 'badge-amber';
    return 'badge-gray';
}

function finishRun(payload) {
    if (payload) {
        resultsSection.classList.remove('hidden');
        resultsSummary.textContent = `${payload.matches.length} matches found`;
        // The table is already populated via candidate_result events
        // but we might want to re-sync with the last known payload.
    }
    if (eventSource) {
        eventSource.close();
    }
}

// --- Utilities ---
downloadBtn.addEventListener('click', async () => {
    const res = await fetch('/api/result');
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'results.json';
    a.click();
});

copyUrlsBtn.addEventListener('click', async () => {
    const res = await fetch('/api/result');
    const data = await res.json();
    const urls = data.matches.join('\n');
    await navigator.clipboard.writeText(urls);
    alert('URLs copied to clipboard!');
});

// Handle Cancel
// (Implementing Cancel would require a button in the UI and a fetch call to /api/cancel/{run_id})
// Let's add it to the UI if it's not there.
