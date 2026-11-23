// Authentication module using Amazon Cognito
const Auth = (() => {
  let currentUser = null;
  let idToken = null;
  
  const cognitoConfig = {
    UserPoolId: CONFIG.COGNITO_USER_POOL_ID,
    ClientId: CONFIG.COGNITO_CLIENT_ID,
  };
  
  const userPool = new AmazonCognitoIdentity.CognitoUserPool(cognitoConfig);
  
  function login() {
    // Redirect to Cognito hosted UI
    const cognitoDomain = CONFIG.COGNITO_DOMAIN;
    const authUrl = `https://${cognitoDomain}.auth.${getRegion()}.amazoncognito.com/login` +
      `?client_id=${CONFIG.COGNITO_CLIENT_ID}` +
      `&response_type=code` +
      `&scope=openid+email+profile` +
      `&redirect_uri=${encodeURIComponent(CONFIG.REDIRECT_URI)}`;
    window.location.href = authUrl;
  }
  
  function handleCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    
    if (!code) {
      console.error('No authorization code in callback');
      return false;
    }
    
    // Exchange code for tokens
    return exchangeCodeForTokens(code);
  }
  
  async function exchangeCodeForTokens(code) {
    try {
      const cognitoDomain = CONFIG.COGNITO_DOMAIN;
      const tokenUrl = `https://${cognitoDomain}.auth.${getRegion()}.amazoncognito.com/oauth2/token`;
      
      const response = await fetch(tokenUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          grant_type: 'authorization_code',
          client_id: CONFIG.COGNITO_CLIENT_ID,
          code: code,
          redirect_uri: CONFIG.REDIRECT_URI,
        }),
      });
      
      if (!response.ok) {
        throw new Error('Token exchange failed');
      }
      
      const tokens = await response.json();
      idToken = tokens.id_token;
      
      // Parse JWT to get user info
      const payload = JSON.parse(atob(idToken.split('.')[1]));
      currentUser = {
        email: payload.email,
        tenantId: payload['custom:tenant_id'],
        name: payload.name || payload.email,
      };
      
      // Store token in sessionStorage
      sessionStorage.setItem('id_token', idToken);
      sessionStorage.setItem('user', JSON.stringify(currentUser));
      
      return true;
    } catch (error) {
      console.error('Token exchange error:', error);
      return false;
    }
  }
  
  function logout() {
    sessionStorage.removeItem('id_token');
    sessionStorage.removeItem('user');
    currentUser = null;
    idToken = null;
    
    const cognitoDomain = CONFIG.COGNITO_DOMAIN;
    const logoutUrl = `https://${cognitoDomain}.auth.${getRegion()}.amazoncognito.com/logout` +
      `?client_id=${CONFIG.COGNITO_CLIENT_ID}` +
      `&logout_uri=${encodeURIComponent(window.location.origin)}`;
    window.location.href = logoutUrl;
  }
  
  function getCurrentUser() {
    if (currentUser) return currentUser;
    
    const stored = sessionStorage.getItem('user');
    if (stored) {
      currentUser = JSON.parse(stored);
      idToken = sessionStorage.getItem('id_token');
      return currentUser;
    }
    return null;
  }
  
  function getIdToken() {
    return idToken || sessionStorage.getItem('id_token');
  }
  
  function isAuthenticated() {
    return !!getIdToken();
  }
  
  function getRegion() {
    // Extract region from Cognito User Pool ID (format: region_XXXXX)
    return CONFIG.COGNITO_USER_POOL_ID.split('_')[0];
  }
  
  return { login, handleCallback, logout, getCurrentUser, getIdToken, isAuthenticated };
})();