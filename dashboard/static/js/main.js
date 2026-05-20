document.addEventListener('DOMContentLoaded', () => {
    // --- State ---
    let currentView = 'workflows-view';
    let currentRunId = null;
    let sseSource = null;
    let autoScroll = true;

    // --- DOM Elements ---
    const navItems = document.querySelectorAll('.nav-item');
    const viewSections = document.querySelectorAll('.view-section');
    const btnRunWorkflow = document.getElementById('run-workflow-btn');
    const btnRunDate = document.getElementById('run-date-btn');
    const runDatePicker = document.getElementById('run-date-picker');
    const workflowDateInput = document.getElementById('workflow-date-input');
    const runForceCheckbox = document.getElementById('run-force-checkbox');
    const btnRunSelectedDate = document.getElementById('run-selected-date-btn');
    const btnCloseRunDatePicker = document.getElementById('close-run-date-picker');
    const workflowsList = document.getElementById('workflows-list');
    const btnBackToWorkflows = document.getElementById('back-to-workflows');
    const btnRetryWorkflow = document.getElementById('retry-workflow-btn');
    const artifactsFilterDate = document.getElementById('artifact-filter-date');
    const artifactFilterApply = document.getElementById('artifact-filter-apply');
    const artifactFilterClear = document.getElementById('artifact-filter-clear');
    const artifactsListContainer = document.getElementById('artifacts-list');
    
    // Detail View Elements
    const detailTitle = document.getElementById('detail-workflow-title');
    const detailStatus = document.getElementById('detail-workflow-status');
    const stepsTimeline = document.getElementById('steps-timeline');
    const logsContainer = document.getElementById('logs-container');
    const currentStepLabel = document.getElementById('current-step-label');
    const toast = document.getElementById('toast');
    const toastMessage = document.getElementById('toast-message');

    // --- Utility Functions ---
    const showToast = (message) => {
        toastMessage.textContent = message;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 5000);
    };

    const formatDate = (isoString) => {
        if (!isoString) return '-';
        const d = new Date(isoString);
        return d.toLocaleString();
    };

    const formatDuration = (seconds) => {
        if (seconds == null) return '-';
        if (seconds < 60) return `${Math.floor(seconds)}s`;
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}m ${s}s`;
    };

    const getStatusIcon = (status) => {
        switch(status) {
            case 'Success': return 'check_circle';
            case 'Failed': return 'cancel';
            case 'Running': return 'sync';
            case 'Skipped': return 'do_not_disturb_on';
            default: return 'pending';
        }
    };

    const getStatusClass = (status) => {
        switch(status) {
            case 'Success': return 'status-success';
            case 'Failed': return 'status-failed';
            case 'Running': return 'status-running';
            case 'Skipped': return 'status-skipped';
            default: return 'status-pending';
        }
    };

    let artifactRuns = [];
    let artifactFilterDateValue = '';

    const setDateInputLimits = () => {
        const today = new Date().toISOString().split('T')[0];
        workflowDateInput.max = today;
        artifactsFilterDate.max = today;
        workflowDateInput.value = today;
    };

    const closeRunDatePicker = () => {
        runDatePicker.classList.add('hidden');
    };

    const openRunDatePicker = () => {
        runDatePicker.classList.toggle('hidden');
        if (!runDatePicker.classList.contains('hidden')) {
            workflowDateInput.focus();
        }
    };

    const handleDocumentClick = (event) => {
        const target = event.target;
        if (!runDatePicker.contains(target) && !btnRunDate.contains(target)) {
            runDatePicker.classList.add('hidden');
        }
    };

    const runWorkflowForDate = async (dateStr = null) => {
        btnRunWorkflow.disabled = true;
        btnRunDate.disabled = true;
        const originalLabel = btnRunWorkflow.innerHTML;
        btnRunWorkflow.innerHTML = '<span class="material-symbols-outlined spinning">sync</span> Starting...';

        try {
            const payload = {};
            if (dateStr) payload.date = dateStr;
            if (runForceCheckbox && runForceCheckbox.checked) payload.force = true;

            const options = {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: Object.keys(payload).length ? JSON.stringify(payload) : null
            };
            const res = await fetch('/api/workflow/run', options);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Failed to start run');

            showToast('Workflow started successfully.');
            closeRunDatePicker();
            openRunDetails(data.run_id);
        } catch (error) {
            showToast(error.message);
        } finally {
            btnRunWorkflow.disabled = false;
            btnRunDate.disabled = false;
            btnRunWorkflow.innerHTML = originalLabel;
        }
    };

    // --- Navigation ---
    const switchView = (targetId) => {
        currentView = targetId;
        navItems.forEach(btn => {
            if(btn.dataset.target === targetId) btn.classList.add('active');
            else btn.classList.remove('active');
        });
        viewSections.forEach(section => {
            if(section.id === targetId) section.classList.add('active');
            else section.classList.remove('active');
        });

        if (targetId === 'workflows-view') {
            loadWorkflows();
            if (sseSource) {
                sseSource.close();
                sseSource = null;
            }
        } else if (targetId === 'artifacts-view') {
            loadArtifacts();
        }
    };

    navItems.forEach(btn => {
        btn.addEventListener('click', () => switchView(btn.dataset.target));
    });

    btnBackToWorkflows.addEventListener('click', () => switchView('workflows-view'));

    // --- API Interactions ---
    const loadWorkflows = async () => {
        try {
            const res = await fetch('/api/workflow/runs');
            const data = await res.json();
            renderWorkflows(data);
        } catch (error) {
            showToast('Failed to load workflows.');
            workflowsList.innerHTML = '<div class="loading-state"><p>Error loading workflows.</p></div>';
        }
    };

    const loadArtifacts = async () => {
        try {
            const res = await fetch('/api/artifacts');
            const data = await res.json();
            artifactRuns = Array.isArray(data) ? data : [];
            renderArtifacts(artifactRuns);
        } catch (error) {
            showToast('Failed to load artifacts.');
        }
    };

    const loadRunDetails = async (runId) => {
        try {
            const res = await fetch(`/api/workflow/runs/${runId}`);
            const data = await res.json();
            renderRunDetails(data);
        } catch (error) {
            showToast('Failed to load run details.');
        }
    };

    const triggerRun = async () => {
        await runWorkflowForDate();
    };

    const retryRun = async () => {
        if (!currentRunId) return;
        btnRetryWorkflow.disabled = true;
        btnRetryWorkflow.innerHTML = '<span class="material-symbols-outlined spinning">sync</span> Retrying...';
        try {
            const res = await fetch(`/api/workflow/runs/${currentRunId}/retry`, { method: 'POST' });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Failed to retry run');
            
            showToast('Workflow retried successfully.');
            openRunDetails(data.run_id);
        } catch (error) {
            showToast(error.message);
        } finally {
            btnRetryWorkflow.disabled = false;
            btnRetryWorkflow.innerHTML = '<span class="material-symbols-outlined">replay</span> Retry Failed Steps';
        }
    };

    btnRunWorkflow.addEventListener('click', triggerRun);
    btnRunDate.addEventListener('click', openRunDatePicker);
    btnRunSelectedDate.addEventListener('click', () => {
        const selectedDate = workflowDateInput.value;
        if (!selectedDate) {
            showToast('Please select a valid date before running.');
            return;
        }
        runWorkflowForDate(selectedDate);
    });
    btnCloseRunDatePicker.addEventListener('click', () => {
        closeRunDatePicker();
    });
    document.addEventListener('click', handleDocumentClick);
    artifactFilterApply.addEventListener('click', () => {
        artifactFilterDateValue = artifactsFilterDate.value;
        renderArtifacts(artifactRuns);
    });
    artifactFilterClear.addEventListener('click', () => {
        artifactsFilterDate.value = '';
        artifactFilterDateValue = '';
        renderArtifacts(artifactRuns);
    });
    btnRetryWorkflow.addEventListener('click', retryRun);

    setDateInputLimits();

    // --- Rendering ---
    const renderWorkflows = (runs) => {
        if (!runs || runs.length === 0) {
            workflowsList.innerHTML = '<div class="loading-state"><p>No workflow runs found.</p></div>';
            return;
        }

        workflowsList.innerHTML = runs.map(run => `
            <div class="workflow-card" onclick="openRunDetails(${run.id})">
                <div class="workflow-card-left">
                    <div class="workflow-card-icon">
                        <span class="material-symbols-outlined ${run.status === 'Running' ? 'spinning' : ''}" style="color: var(--color-${run.status.toLowerCase()}-text, var(--text-secondary))">
                            ${getStatusIcon(run.status)}
                        </span>
                    </div>
                    <div class="workflow-card-info">
                        <h3>DA-Workflow Execution (${run.date})</h3>
                        <div class="workflow-card-meta">
                            <span class="meta-item"><span class="material-symbols-outlined">tag</span> Run #${run.id}</span>
                            <span class="meta-item"><span class="material-symbols-outlined">event</span> ${formatDate(run.started_at)}</span>
                            <span class="meta-item"><span class="material-symbols-outlined">timer</span> ${formatDuration(run.duration_seconds)}</span>
                            <span class="meta-item"><span class="material-symbols-outlined">bolt</span> ${run.trigger_type}</span>
                        </div>
                    </div>
                </div>
                <div>
                    <span class="status-badge ${getStatusClass(run.status)}">${run.status}</span>
                </div>
            </div>
        `).join('');
    };

    const renderArtifacts = (runs) => {
        const artifactsList = document.getElementById('artifacts-list');
        if (!runs || runs.length === 0) {
            artifactsList.innerHTML = '<div class="empty-state"><p>No successful runs found.</p></div>';
            return;
        }

        const sortedRuns = [...runs].sort((a, b) => b.date.localeCompare(a.date));
        const filteredRuns = artifactFilterDateValue
            ? sortedRuns.filter(run => run.date === artifactFilterDateValue)
            : sortedRuns;

        if (!filteredRuns.length) {
            artifactsList.innerHTML = '<div class="empty-state"><p>No runs match the selected date.</p></div>';
            return;
        }

        artifactsList.innerHTML = filteredRuns.map(run => `
            <details class="artifact-card">
                <summary class="artifact-card-header">
                    <div class="artifact-header-left">
                        <div class="artifact-title">${run.date}</div>
                        <div class="artifact-meta">
                            <span class="status-badge ${getStatusClass(run.status)}">${run.status}</span>
                            <span>${run.trigger_type}</span>
                            <span>${formatDuration(run.duration_seconds)}</span>
                        </div>
                    </div>
                    <span class="artifact-expand">Expand</span>
                </summary>
                <div class="artifact-card-body">
                    ${run.files && run.files.length ? run.files.map(file => `
                        <div class="artifact-file-row">
                            <div>
                                <div class="artifact-file-label">${file.label}</div>
                                <div class="artifact-file-path">${file.category}/${file.filename}</div>
                            </div>
                            <a class="btn artifact-download-btn" href="/api/artifacts/${run.id}/download-file/${encodeURIComponent(file.filename)}" target="_blank">
                                <span class="material-symbols-outlined">download</span>
                                Download
                            </a>
                        </div>
                    `).join('') : '<div class="empty-state"><p>No artifact files available.</p></div>'}
                </div>
            </details>
        `).join('');
    };

    window.openRunDetails = (runId) => {
        currentRunId = runId;
        logsContainer.innerHTML = '';
        currentStepLabel.textContent = 'Overall';
        switchView('workflow-detail-view');
        loadRunDetails(runId);
        setupSSE();
    };

    const renderRunDetails = (run) => {
        detailTitle.textContent = `Workflow Run #${run.id} (${run.date})`;
        detailStatus.textContent = run.status;
        detailStatus.className = `status-badge ${getStatusClass(run.status)}`;

        if (run.status === 'Failed') {
            btnRetryWorkflow.classList.remove('hidden');
        } else {
            btnRetryWorkflow.classList.add('hidden');
        }

        if (!run.steps || run.steps.length === 0) {
            stepsTimeline.innerHTML = '<p>No steps recorded.</p>';
            return;
        }

        stepsTimeline.innerHTML = run.steps.map(step => `
            <div class="step-item" id="step-${step.step_index}" onclick="selectStep(${step.step_index}, \`${encodeURIComponent(step.log_output || '')}\`, '${step.name}')">
                <div class="step-icon ${step.status.toLowerCase()}">
                    <span class="material-symbols-outlined ${step.status === 'Running' ? 'spinning' : ''}">
                        ${getStatusIcon(step.status)}
                    </span>
                </div>
                <div class="step-content">
                    <span class="step-name">${step.name}</span>
                    <span class="step-duration" id="step-duration-${step.step_index}">${formatDuration(step.duration_seconds)}</span>
                </div>
            </div>
        `).join('');

        // Select first step by default or show overall? 
        // Let's gather all logs to show overall
        const allLogs = run.steps.map(s => s.log_output).join('');
        if (allLogs) {
            logsContainer.textContent = allLogs;
            scrollToBottom();
        }
    };

    window.selectStep = (index, encodedLogs, name) => {
        // Handle UI highlight
        document.querySelectorAll('.step-item').forEach(el => el.classList.remove('active'));
        const stepEl = document.getElementById(`step-${index}`);
        if(stepEl) stepEl.classList.add('active');

        currentStepLabel.textContent = name;
        logsContainer.textContent = decodeURIComponent(encodedLogs);
        scrollToBottom();
    };

    const scrollToBottom = () => {
        if (autoScroll) {
            logsContainer.scrollTop = logsContainer.scrollHeight;
        }
    };

    logsContainer.addEventListener('scroll', () => {
        const isAtBottom = logsContainer.scrollHeight - logsContainer.scrollTop <= logsContainer.clientHeight + 10;
        autoScroll = isAtBottom;
    });

    // --- SSE ---
    const setupSSE = () => {
        if (sseSource) {
            sseSource.close();
        }
        sseSource = new EventSource('/api/workflow/stream');
        
        sseSource.onmessage = (e) => {
            const event = JSON.parse(e.data);
            
            // Check if event is for current run
            if (event.run_id === currentRunId) {
                // If it's a step log, append to overall container and update timeline
                if (event.message) {
                    logsContainer.textContent += event.message;
                    scrollToBottom();
                }

                // Periodically reload run details to get status updates
                // We do it loosely, e.g. every few events or specifically when status changes.
                // For a smooth UI, we'll just reload details on every specific step complete.
                if (event.message && event.message.includes("Completed step")) {
                    loadRunDetails(currentRunId);
                }
                if (event.message && event.message.includes("failed")) {
                    loadRunDetails(currentRunId);
                }
            }
        };

        sseSource.onerror = () => {
            console.log("SSE Connection lost. Reconnecting...");
        };
    };

    // Initialize
    loadWorkflows();
});
