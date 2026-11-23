// Main application logic
const App = (() => {
  let currentView = 'dashboard';
  
  async function init() {
    // Check if we're on the callback page
    if (window.location.pathname.includes('callback.html')) {
      const success = await Auth.handleCallback();
      if (success) {
        window.location.href = '/';
      } else {
        showNotification('Login failed', 'error');
      }
      return;
    }
    
    // Check authentication
    if (!Auth.isAuthenticated()) {
      showView('login');
      return;
    }
    
    const user = Auth.getCurrentUser();
    if (!user || !user.tenantId) {
      showNotification('No tenant associated with your account. Contact your administrator.', 'error');
      Auth.logout();
      return;
    }
    
    // Show main UI
    document.getElementById('nav').style.display = 'flex';
    showView('dashboard');
    setupNavigation();
    setupEventListeners();
    
    // Load initial data
    loadDashboard();
  }
  
  function setupNavigation() {
    document.querySelectorAll('nav a').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const view = e.target.dataset.view;
        showView(view);
        loadViewData(view);
      });
    });
  }
  
  function setupEventListeners() {
    document.getElementById('login-btn').addEventListener('click', Auth.login);
    document.getElementById('logout-btn').addEventListener('click', Auth.logout);
    
    document.getElementById('add-rule-btn').addEventListener('click', () => {
      document.getElementById('rule-form').style.display = 'block';
    });
    
    document.getElementById('cancel-rule-btn').addEventListener('click', () => {
      document.getElementById('rule-form').style.display = 'none';
    });
    
    document.getElementById('rule-form-element').addEventListener('submit', handleCreateRule);
    
    document.getElementById('add-webhook-btn').addEventListener('click', () => {
      document.getElementById('webhook-form').style.display = 'block';
    });
    
    document.getElementById('cancel-webhook-btn').addEventListener('click', () => {
      document.getElementById('webhook-form').style.display = 'none';
    });
    
    document.getElementById('webhook-form-element').addEventListener('submit', handleCreateWebhook);
    
    document.getElementById('settings-form').addEventListener('submit', handleUpdateSettings);
  }
  
  function showView(viewName) {
    document.querySelectorAll('.view').forEach(v => v.style.display = 'none');
    document.getElementById(`${viewName}-view`).style.display = 'block';
    
    document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
    const activeLink = document.querySelector(`nav a[data-view="${viewName}"]`);
    if (activeLink) activeLink.classList.add('active');
    
    currentView = viewName;
  }
  
  async function loadViewData(view) {
    switch (view) {
      case 'dashboard': await loadDashboard(); break;
      case 'rules': await loadRules(); break;
      case 'webhooks': await loadWebhooks(); break;
      case 'audit': await loadAudit(); break;
      case 'settings': await loadSettings(); break;
    }
  }
  
  async function apiCall(method, path, body = null) {
    const token = Auth.getIdToken();
    const options = {
      method,
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    };
    
    if (body) options.body = JSON.stringify(body);
    
    const response = await fetch(`${CONFIG.API_URL}${path}`, options);
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'API call failed');
    }
    
    return response.json();
  }
  
  async function loadDashboard() {
    try {
      const [me, status, history] = await Promise.all([
        apiCall('GET', '/me'),
        apiCall('GET', '/me/status'),
        apiCall('GET', '/me/history?days=30'),
      ]);
      
      // Tenant status card
      const statusBadge = `<span class="status-badge ${status.overall_health}">${status.overall_health}</span>`;
      document.getElementById('tenant-status').innerHTML = `
        <p><strong>${me.display_name}</strong></p>
        <p>Status: ${statusBadge}</p>
        <p>Tenant ID: <code>${me.tenant_id}</code></p>
      `;
      
      // Health score
      const scoreEl = document.getElementById('health-score');
      scoreEl.textContent = status.health_score;
      scoreEl.className = 'big-number';
      if (status.health_score < 50) scoreEl.classList.add('danger');
      else if (status.health_score < 80) scoreEl.classList.add('warning');
      
      // Resources
      document.getElementById('resources').innerHTML = `
        <p>Audit Records: <strong>${status.resources.audit_records}</strong></p>
        <p>Conversations: <strong>${status.resources.conversations}</strong></p>
        <p>KB Documents: <strong>${status.resources.kb_documents}</strong></p>
        <p>Feedback Records: <strong>${status.resources.feedback_records}</strong></p>
      `;
      
      // Draw trend chart
      drawTrendChart(history.history);
      
    } catch (error) {
      showNotification(`Failed to load dashboard: ${error.message}`, 'error');
    }
  }
  
  function drawTrendChart(history) {
    const canvas = document.getElementById('trend-chart');
    const ctx = canvas.getContext('2d');
    
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    if (!history || history.length === 0) {
      ctx.fillText('No history data available', 20, 100);
      return;
    }
    
    const padding = 40;
    const chartWidth = canvas.width - padding * 2;
    const chartHeight = canvas.height - padding * 2;
    
    // Draw axes
    ctx.strokeStyle = '#ddd';
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, canvas.height - padding);
    ctx.lineTo(canvas.width - padding, canvas.height - padding);
    ctx.stroke();
    
    // Draw line
    ctx.strokeStyle = '#3498db';
    ctx.lineWidth = 2;
    ctx.beginPath();
    
    history.forEach((point, i) => {
      const x = padding + (i / (history.length - 1)) * chartWidth;
      const y = padding + chartHeight - (point.health_score / 100) * chartHeight;
      
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    
    ctx.stroke();
    
    // Draw points
    ctx.fillStyle = '#3498db';
    history.forEach((point, i) => {
      const x = padding + (i / (history.length - 1)) * chartWidth;
      const y = padding + chartHeight - (point.health_score / 100) * chartHeight;
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
    });
    
    // Labels
    ctx.fillStyle = '#666';
    ctx.font = '12px sans-serif';
    ctx.fillText('100', 10, padding + 5);
    ctx.fillText('0', 20, canvas.height - padding);
    ctx.fillText(history[0].snapshot_date, padding, canvas.height - padding + 15);
    ctx.fillText(history[history.length - 1].snapshot_date, canvas.width - padding - 60, canvas.height - padding + 15);
  }
  
  async function loadRules() {
    try {
      const data = await apiCall('GET', '/me/rules');
      const list = document.getElementById('rules-list');
      
      if (data.rules.length === 0) {
        list.innerHTML = '<p class="info">No custom rules defined. Click "Add Rule" to create one.</p>';
        return;
      }
      
      list.innerHTML = data.rules.map(rule => `
        <div class="list-item">
          <div class="list-item-info">
            <strong>${rule.description || rule.type}</strong>
            <small>${rule.type} | ${rule.metric} | Impact: ${rule.impact > 0 ? '+' : ''}${rule.impact}</small>
          </div>
          <button class="btn-danger" data-rule-id="${rule.rule_id}">Delete</button>
        </div>
      `).join('');
      
      // Attach delete handlers
      list.querySelectorAll('.btn-danger').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (confirm('Delete this rule?')) {
            await apiCall('DELETE', `/me/rules/${btn.dataset.ruleId}`);
            showNotification('Rule deleted', 'success');
            loadRules();
          }
        });
      });
    } catch (error) {
      showNotification(`Failed to load rules: ${error.message}`, 'error');
    }
  }
  
  async function handleCreateRule(e) {
    e.preventDefault();
    
    const rule = {
      type: document.getElementById('rule-type').value,
      metric: document.getElementById('rule-metric').value,
      operator: document.getElementById('rule-operator').value,
      value: parseFloat(document.getElementById('rule-value').value),
      impact: parseInt(document.getElementById('rule-impact').value),
      description: document.getElementById('rule-description').value,
      created_by: Auth.getCurrentUser().email,
    };
    
    try {
      await apiCall('POST', '/me/rules', rule);
      showNotification('Rule created', 'success');
      document.getElementById('rule-form').style.display = 'none';
      document.getElementById('rule-form-element').reset();
      loadRules();
    } catch (error) {
      showNotification(`Failed to create rule: ${error.message}`, 'error');
    }
  }
  
  async function loadWebhooks() {
    try {
      const data = await apiCall('GET', '/me/webhooks');
      const list = document.getElementById('webhooks-list');
      
      if (data.webhooks.length === 0) {
        list.innerHTML = '<p class="info">No webhooks configured. Click "Add Webhook" to create one.</p>';
        return;
      }
      
      list.innerHTML = data.webhooks.map(webhook => `
        <div class="list-item">
          <div class="list-item-info">
            <strong>${webhook.webhook_id}</strong>
            <small>Platform: ${webhook.platform} | Enabled: ${webhook.enabled ? 'Yes' : 'No'}</small>
          </div>
          <button class="btn-danger" data-webhook-id="${webhook.webhook_id}">Delete</button>
        </div>
      `).join('');
      
      list.querySelectorAll('.btn-danger').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (confirm('Delete this webhook?')) {
            await apiCall('DELETE', `/me/webhooks/${btn.dataset.webhookId}`);
            showNotification('Webhook deleted', 'success');
            loadWebhooks();
          }
        });
      });
    } catch (error) {
      showNotification(`Failed to load webhooks: ${error.message}`, 'error');
    }
  }
  
  async function handleCreateWebhook(e) {
    e.preventDefault();
    
    const webhook = {
      webhook_id: document.getElementById('webhook-id').value,
      platform: document.getElementById('webhook-platform').value,
      created_by: Auth.getCurrentUser().email,
    };
    
    try {
      await apiCall('POST', '/me/webhooks', webhook);
      showNotification('Webhook created. Admin must add URL to secret.', 'info');
      document.getElementById('webhook-form').style.display = 'none';
      document.getElementById('webhook-form-element').reset();
      loadWebhooks();
    } catch (error) {
      showNotification(`Failed to create webhook: ${error.message}`, 'error');
    }
  }
  
  async function loadAudit() {
    try {
      const data = await apiCall('GET', '/me/audit?limit=100');
      const list = document.getElementById('audit-list');
      
      if (data.audit_log.length === 0) {
        list.innerHTML = '<p class="info">No audit entries found.</p>';
        return;
      }
      
      list.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Tool</th>
              <th>Operation</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            ${data.audit_log.map(entry => `
              <tr>
                <td>${new Date(entry.timestamp).toLocaleString()}</td>
                <td>${entry.tool_name}</td>
                <td>${entry.operation_type}</td>
                <td>${JSON.parse(entry.result_summary || '{}').success ? '✓' : '✗'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    } catch (error) {
      showNotification(`Failed to load audit log: ${error.message}`, 'error');
    }
  }
  
  async function loadSettings() {
    try {
      const me = await apiCall('GET', '/me');
      
      document.getElementById('setting-display-name').value = me.display_name || '';
      document.getElementById('setting-contact-email').value = me.contact_email || '';
      document.getElementById('setting-timezone').value = me.timezone || '';
      document.getElementById('setting-company-name').value = me.branding?.company_name || '';
      document.getElementById('setting-primary-color').value = me.branding?.primary_color || '#2c3e50';
      document.getElementById('setting-allowed-users').value = (me.allowed_users || []).join(', ');
    } catch (error) {
      showNotification(`Failed to load settings: ${error.message}`, 'error');
    }
  }
  
  async function handleUpdateSettings(e) {
    e.preventDefault();
    
    const updates = {
      display_name: document.getElementById('setting-display-name').value,
      contact_email: document.getElementById('setting-contact-email').value,
      timezone: document.getElementById('setting-timezone').value,
      branding: {
        company_name: document.getElementById('setting-company-name').value,
        primary_color: document.getElementById('setting-primary-color').value,
      },
      allowed_users: document.getElementById('setting-allowed-users').value
        .split(',')
        .map(e => e.trim())
        .filter(e => e),
    };
    
    try {
      await apiCall('PUT', '/me', updates);
      showNotification('Settings updated', 'success');
    } catch (error) {
      showNotification(`Failed to update settings: ${error.message}`, 'error');
    }
  }
  
  function showNotification(message, type = 'info') {
    const el = document.getElementById('notification');
    el.textContent = message;
    el.className = `notification ${type}`;
    el.style.display = 'block';
    
    setTimeout(() => { el.style.display = 'none'; }, 5000);
  }
  
  return { init };
})();

// Initialize on page load
document.addEventListener('DOMContentLoaded', App.init);