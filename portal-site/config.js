// Portal configuration — populated during deployment
const CONFIG = {
  COGNITO_USER_POOL_ID: '__COGNITO_USER_POOL_ID__',
  COGNITO_CLIENT_ID: '__COGNITO_CLIENT_ID__',
  COGNITO_DOMAIN: '__COGNITO_DOMAIN__',
  API_URL: '__API_URL__',
  REDIRECT_URI: window.location.origin + '/callback.html',
};