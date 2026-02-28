const toggle = document.getElementById('darkToggle');

if (localStorage.getItem('darkMode') === 'true') {
  document.body.classList.add('dark');  // ← 'dark', not 'dark-mode'
  toggle.checked = true;
}

toggle.addEventListener('change', () => {
  const isDark = toggle.checked;
  document.body.classList.toggle('dark', isDark);  // ← 'dark', not 'dark-mode'
  localStorage.setItem('darkMode', isDark);
});