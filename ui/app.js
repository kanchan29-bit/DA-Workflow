// State management
let pipelineData = {
    steps: [],
    is_running: false,
    current_step_index: -1
};

let artifactsData = [];
let logEventSource = null;

// DOM Elements
const btnBuild = document.getElementById('btn-build');
const globalStatus = document.getElementById('global-status');
const pipelineContainer = document.getElementById('pipeline-stages');
const consoleOutput = document.getElementById('console-output');
const btnClearLogs = document.getElementById('btn-clear-logs');

// Views
const navItems = document.querySelectorAll('.nav-item');
const views = document.querySelectorAll('.view');

// Navigation Logic
navItems.forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        const viewId = `view-${item.id.replace('nav-', '')}`;
        
        navItems.forEach(nav => nav.classList.remove('active'));
        item.classList.add('active');
        
        views.forEach(view => {
            if (view.id === viewId) {
                view.classList.remove('hidden');
            } else {
                view.classList.add('hidden');
            }
        });
    });
});

// Fetch Pipeline Data
async function fetchStatus() {
    try {
        const response = await fetch('/api/pipeline');
        pipelineData = await response.json();
        updateUI();
    } catch (error) {
        console.error('Failed to fetch status:', error);
    }
}

// Update UI
function updateUI() {
    // Update Button
    btnBuild.disabled = pipelineData.is_running;
    
    // Update Global Badge
    globalStatus.className = 'status-badge ' + (pipelineData.is_running ? 'running' : 'idle');
    globalStatus.textContent = pipelineData.is_running ? 'Running' : 'Idle';

    // Render Pipeline Stages
    if (pipelineData.steps.length > 0) {
        pipelineContainer.innerHTML = pipelineData.steps.map((step, index) => {
            const isCurrent = index === pipelineData.current_step_index;
            const statusClass = step.status;
            const icon = step.status === 'success' ? 'check_circle' : 
                         step.status === 'failed' ? 'error' : 
                         step.status === 'running' ? 'pending' : 'circle';
            
            return `
                <div class="stage-card ${statusClass} ${isCurrent ? 'current' : ''}">
                    <div class="stage-icon">
                        <span class="material-symbols-outlined">${icon}</span>
                    </div>
                    <div class="stage-info">
                        <div class="stage-name">${step.name}</div>
                        <div class="stage-script">${step.script}</div>
                    </div>
                    <div class="stage-meta">
                        <div class="stage-status">${step.status.toUpperCase()}</div>
                        <div class="stage-duration">${step.duration || '--'}</div>
                    </div>
                </div>
            `;
        }).join('');
    }
}

// Start Build
btnBuild.addEventListener('click', async () => {
    if (pipelineData.is_running) return;
    
    try {
        const response = await fetch('/api/execute', { method: 'POST' });
        if (response.ok) {
            pipelineData.is_running = true;
            updateUI();
            startLogStream();
            // Switch to logs view
            document.getElementById('nav-logs').click();
        }
    } catch (error) {
        alert('Failed to start build: ' + error);
    }
});

// Clear Logs
btnClearLogs.addEventListener('click', () => {
    consoleOutput.innerHTML = '<div class="empty-state">Logs cleared.</div>';
});

// Log Streaming
function startLogStream() {
    if (logEventSource) {
        logEventSource.close();
    }

    consoleOutput.innerHTML = ''; // Clear previous logs
    
    logEventSource = new EventSource('/api/logs');
    
    logEventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const logLine = document.createElement('div');
        logLine.textContent = data.message;
        
        // Add color coding
        if (data.message.includes('ERROR') || data.message.includes('failed')) {
            logLine.style.color = '#ef4444';
        } else if (data.message.includes('success') || data.message.includes('completed')) {
            logLine.style.color = '#22c55e';
        } else if (data.message.includes('Starting')) {
            logLine.style.color = '#3b82f6';
            logLine.style.fontWeight = 'bold';
        }

        consoleOutput.appendChild(logLine);
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
        
        // Periodically refresh status while logs are coming in
        fetchStatus();
    };

    logEventSource.onerror = () => {
        console.error('Log stream error');
        logEventSource.close();
    };
}

// Fetch Artifacts
async function fetchArtifacts() {
    try {
        const response = await fetch('/api/outputs');
        artifactsData = await response.json();
        renderArtifacts();
    } catch (error) {
        console.error('Failed to fetch artifacts:', error);
    }
}

// Render Artifacts
function renderArtifacts() {
    const list = document.getElementById('artifacts-list');
    if (artifactsData.length === 0) {
        list.innerHTML = '<div class="empty-state">No artifacts found.</div>';
        return;
    }

    list.innerHTML = artifactsData.map(file => `
        <div class="artifact-card">
            <div class="artifact-icon">
                <span class="material-symbols-outlined">description</span>
            </div>
            <div class="artifact-details">
                <h4>${file.name}</h4>
                <p>${file.category} • ${file.size}</p>
                <p style="font-size: 10px; opacity: 0.7;">${file.modified}</p>
            </div>
        </div>
    `).join('');
}

// Polling for status if not running (to catch external updates or refresh)
setInterval(() => {
    if (!pipelineData.is_running) {
        fetchStatus();
        fetchArtifacts();
    }
}, 3000);

// Initial Load
fetchStatus();
fetchArtifacts();
if (pipelineData.is_running) {
    startLogStream();
}
