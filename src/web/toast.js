(function(root) {
  'use strict';
  let timer;
  root.PolarisToast = function(message) {
    let toast = document.getElementById('polaris-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'polaris-toast'; toast.className = 'polaris-toast';
      toast.setAttribute('role','status'); toast.setAttribute('aria-live','polite');
      document.body.appendChild(toast);
    }
    clearTimeout(timer);
    toast.textContent = message;
    toast.classList.add('is-visible');
    timer = setTimeout(() => toast.classList.remove('is-visible'), 4000);
  };
})(window);
