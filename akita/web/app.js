function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatUptime(timestamp) {
    const seconds = Math.floor((Date.now() / 1000) - timestamp);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
    const hours = Math.floor(minutes / 60);
    return `${hours}h ${minutes % 60}m`;
}

let serverSettings = {};

async function fetchStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        serverSettings = data; // store to populate modal
        const dot = document.getElementById('server-dot');
        const statusText = document.getElementById('server-status-text');
        const btnStart = document.getElementById('btn-start');
        const btnStop = document.getElementById('btn-stop');
        
        if (data.is_running) {
            dot.className = 'dot active';
            statusText.textContent = `Online: ${data.nickname}`;
            document.getElementById('active-clients').textContent = data.active_clients;
            document.getElementById('resolution').textContent = data.resolution;
            btnStart.style.display = 'none';
            btnStop.style.display = 'inline-block';
            
            const encoderStatus = document.getElementById('encoder-status');
            if (data.ffmpeg_running) {
                encoderStatus.innerHTML = '<span style="color: var(--accent-orange)">Encoding</span>';
            } else {
                encoderStatus.textContent = 'Idle';
            }
        } else {
            dot.className = 'dot';
            statusText.textContent = 'Offline';
            document.getElementById('active-clients').textContent = '0';
            document.getElementById('encoder-status').textContent = 'Stopped';
            btnStart.style.display = 'inline-block';
            btnStop.style.display = 'none';
        }
    } catch (e) {
        document.getElementById('server-dot').className = 'dot';
        document.getElementById('server-status-text').textContent = 'Disconnected';
    }
}

async function fetchClients() {
    try {
        const response = await fetch('/api/clients');
        const clients = await response.json();
        
        const tbody = document.getElementById('clients-body');
        let totalBytes = 0;
        
        if (clients.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No peers currently connected.</td></tr>`;
        } else {
            let html = '';
            clients.forEach(c => {
                totalBytes += c.bytes_sent;
                html += `
                    <tr>
                        <td style="font-family: monospace; color: var(--text-white)">${c.id}</td>
                        <td>${formatUptime(c.connected_at)}</td>
                        <td>${formatBytes(c.bytes_sent)}</td>
                        <td><span class="badge">ACTIVE</span></td>
                        <td><button class="btn btn-danger" style="padding: 0.2rem 0.5rem; font-size: 0.75rem;" onclick="kickClient('${c.full_id}')">Kick</button></td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;
        }
        
        document.getElementById('bandwidth').textContent = formatBytes(totalBytes);
        
    } catch (e) {
        console.error("Failed to fetch clients", e);
    }
}

// Controls
async function controlServer(action) {
    try {
        await fetch(`/api/control/${action}`, { method: 'POST' });
        fetchStatus();
    } catch (e) { console.error(e); }
}

async function kickClient(id) {
    if (!confirm('Are you sure you want to kick this peer?')) return;
    try {
        await fetch(`/api/clients/${id}`, { method: 'DELETE' });
        fetchClients();
    } catch (e) { console.error(e); }
}

// Modal logic
function openSettings() {
    document.getElementById('input-res').value = serverSettings.resolution || '1280x720';
    document.getElementById('input-fps').value = serverSettings.fps || 20;
    document.getElementById('input-max').value = serverSettings.max_clients !== undefined ? serverSettings.max_clients : 0;
    document.getElementById('settings-modal').classList.add('active');
}

function closeSettings() {
    document.getElementById('settings-modal').classList.remove('active');
}

async function saveSettings() {
    const payload = {
        res: document.getElementById('input-res').value,
        fps: parseInt(document.getElementById('input-fps').value),
        max_clients: parseInt(document.getElementById('input-max').value)
    };
    try {
        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        closeSettings();
        fetchStatus();
    } catch (e) { console.error(e); }
}

// Initial fetch and loop
fetchStatus();
fetchClients();

setInterval(() => {
    fetchStatus();
    fetchClients();
}, 2000);
