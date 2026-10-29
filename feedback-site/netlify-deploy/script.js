/**
 * BITE and POUR — Customer Feedback System
 * Premium Multi-Step Wizard Engine & Visual Interactions
 */

document.addEventListener('DOMContentLoaded', () => {

  /* ──────────────────────────────────────────────────────────────
     0. AMBIENT GOLD PARTICLES
  ────────────────────────────────────────────────────────────── */
  const particleField = document.getElementById('ptField');
  if (particleField) {
    const isReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const count = isReduced ? 0 : 16;
    for (let i = 0; i < count; i++) {
      const p = document.createElement('div');
      p.className = 'particle';
      const size = Math.random() * 4 + 1.5; // 1.5px to 5.5px
      const leftPct = Math.random() * 100;
      const dur = (Math.random() * 16 + 12) + 's'; // 12-28s
      const delay = (Math.random() * 18) + 's';
      p.style.cssText = `
        width: ${size}px;
        height: ${size}px;
        left: ${leftPct}%;
        --dur: ${dur};
        --delay: -${delay};
        opacity: 0;
        filter: blur(${size < 3 ? 0 : 1}px);
      `;
      particleField.appendChild(p);
    }
  }

  /* ──────────────────────────────────────────────────────────────
     1. DOM ELEMENTS & STATE
  ────────────────────────────────────────────────────────────── */
  const form        = document.getElementById('feedbackForm');
  const submitBtn   = document.getElementById('submitBtn');
  const spinner     = document.getElementById('spinner');
  const submitText  = document.getElementById('submitText');
  const errBanner   = document.getElementById('errBanner');
  const errText     = document.getElementById('errText');
  const thankYou    = document.getElementById('thankyou');
  const pFill       = document.getElementById('pFill');
  const stepLabel   = document.getElementById('stepLabel');
  const stepName    = document.getElementById('stepName');

  const steps = [1, 2, 3, 4].map(n => document.getElementById(`step-${n}`));
  const dots  = [1, 2, 3, 4].map(n => document.getElementById(`pd${n}`));

  let currentStep = 1;

  const stepNames = {
    1: 'Menu Selection',
    2: 'Quality Ratings',
    3: 'Value & Insights',
    4: 'Final Thought'
  };

  const ratingPillLabels = {
    1: '1 ★ — Needs Improvement',
    2: '2 ★ — Below Expectations',
    3: '3 ★ — Satisfactory',
    4: '4 ★ — Very Good',
    5: '5 ★ — Exceptional ✨'
  };

  /* ──────────────────────────────────────────────────────────────
     2. WIZARD STEP NAVIGATION
  ────────────────────────────────────────────────────────────── */
  function goToStep(num) {
    if (num < 1 || num > 4) return;

    hideError();

    // Toggle active state on step cards
    steps.forEach((stepEl, idx) => {
      if (!stepEl) return;
      const stepNum = idx + 1;
      if (stepNum === num) {
        stepEl.classList.add('active');
      } else {
        stepEl.classList.remove('active');
      }
    });

    currentStep = num;

    // Update progress track fill %
    const pct = { 1: 0, 2: 33.3, 3: 66.6, 4: 100 };
    if (pFill) pFill.style.width = `${pct[num]}%`;

    // Update step dots
    dots.forEach((dotEl, idx) => {
      if (!dotEl) return;
      const dotNum = idx + 1;
      dotEl.classList.remove('active', 'done');
      if (dotNum === num) {
        dotEl.classList.add('active');
      } else if (dotNum < num) {
        dotEl.classList.add('done');
      }
    });

    // Update headers
    if (stepLabel) stepLabel.textContent = `Step ${num} of 4`;
    if (stepName)  stepName.textContent  = stepNames[num] || '';

    // Smooth scroll back to progress header for mobile feel
    const navHeader = document.querySelector('.progress-wrap');
    if (navHeader) {
      navHeader.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  /* ──────────────────────────────────────────────────────────────
     3. STEP VALIDATION
  ────────────────────────────────────────────────────────────── */
  function validateStep(num) {
    const formData = new FormData(form);

    if (num === 1) {
      if (!formData.get('item')) {
        showError('Please select what item you tried today.');
        return false;
      }
    }

    if (num === 2) {
      const overall = document.getElementById('overall_rating').value;
      const taste   = document.getElementById('taste_rating').value;
      const pres    = document.getElementById('presentation_rating').value;

      if (!overall) { showError('Please rate your Overall Experience.'); return false; }
      if (!taste)   { showError('Please rate the Taste.'); return false; }
      if (!pres)    { showError('Please rate the Presentation.'); return false; }
    }

    if (num === 3) {
      if (!formData.get('value_rating')) {
        showError('Please indicate if it was worth the price.');
        return false;
      }
    }

    return true;
  }

  /* ──────────────────────────────────────────────────────────────
     4. NAVIGATION BUTTON LISTENERS
  ────────────────────────────────────────────────────────────── */
  document.getElementById('next1')?.addEventListener('click', () => {
    if (validateStep(1)) goToStep(2);
  });

  document.getElementById('next2')?.addEventListener('click', () => {
    if (validateStep(2)) goToStep(3);
  });

  document.getElementById('next3')?.addEventListener('click', () => {
    if (validateStep(3)) goToStep(4);
  });

  document.getElementById('back2')?.addEventListener('click', () => goToStep(1));
  document.getElementById('back3')?.addEventListener('click', () => goToStep(2));
  document.getElementById('back4')?.addEventListener('click', () => goToStep(3));

  // Step dot clicks (direct jump if already reached or valid)
  dots.forEach((dotEl, idx) => {
    if (!dotEl) return;
    const targetStep = idx + 1;
    dotEl.style.cursor = 'pointer';
    dotEl.addEventListener('click', () => {
      if (targetStep < currentStep) {
        goToStep(targetStep);
      } else if (targetStep === currentStep + 1 && validateStep(currentStep)) {
        goToStep(targetStep);
      }
    });
  });

  /* ──────────────────────────────────────────────────────────────
     5. CATEGORY FILTERING (STEP 1)
  ────────────────────────────────────────────────────────────── */
  const catBtns  = document.querySelectorAll('.cat-btn');
  const itemChips = document.querySelectorAll('.pchip');

  catBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      catBtns.forEach(b => b.classList.remove('on'));
      btn.classList.add('on');

      const cat = btn.dataset.cat;
      itemChips.forEach(chip => {
        const chipCat = chip.dataset.cat;
        if (cat === 'all' || chipCat === cat || chipCat === 'all') {
          chip.style.display = 'flex';
        } else {
          chip.style.display = 'none';
        }
      });
    });
  });

  /* ──────────────────────────────────────────────────────────────
     6. PRODUCT CHIP SELECTION
  ────────────────────────────────────────────────────────────── */
  itemChips.forEach(chip => {
    chip.addEventListener('click', () => {
      itemChips.forEach(c => c.classList.remove('on'));
      chip.classList.add('on');
      const radio = chip.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
      hideError();
    });
  });

  /* ──────────────────────────────────────────────────────────────
     7. OPTION CHIPS (STEP 3 & 4)
  ────────────────────────────────────────────────────────────── */
  const optionLabels = document.querySelectorAll('.opt');
  optionLabels.forEach(opt => {
    opt.addEventListener('click', () => {
      // Uncheck siblings in same radiogroup
      const radio = opt.querySelector('input[type="radio"]');
      if (radio) {
        const groupName = radio.name;
        document.querySelectorAll(`input[name="${groupName}"]`).forEach(r => {
          r.closest('.opt')?.classList.remove('on');
        });
        opt.classList.add('on');
        radio.checked = true;
        hideError();
      }
    });
  });

  /* ──────────────────────────────────────────────────────────────
     8. STAR RATING ENGINE
  ────────────────────────────────────────────────────────────── */
  const ratingGroups = document.querySelectorAll('.stars');
  ratingGroups.forEach(group => {
    const fieldName = group.dataset.field;
    const hiddenInput = document.getElementById(fieldName);
    const pill = document.getElementById(`${fieldName}_pill`);
    const starBtns = group.querySelectorAll('.star-btn');

    starBtns.forEach(btn => {
      const val = parseInt(btn.dataset.v, 10);

      // Hover preview
      btn.addEventListener('mouseenter', () => {
        highlightStars(starBtns, val, 'hover');
        if (pill) pill.textContent = ratingPillLabels[val] || '';
      });

      // Mouse leave restore
      group.addEventListener('mouseleave', () => {
        const activeVal = parseInt(hiddenInput?.value, 10) || 0;
        highlightStars(starBtns, activeVal, 'lit');
        if (pill) {
          pill.textContent = activeVal ? ratingPillLabels[activeVal] : 'Tap a star to rate';
        }
      });

      // Click select
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        if (hiddenInput) hiddenInput.value = val;
        highlightStars(starBtns, val, 'lit');
        if (pill) pill.textContent = ratingPillLabels[val];
        hideError();
      });

      // Touch device support
      btn.addEventListener('touchend', (e) => {
        e.preventDefault();
        btn.click();
      });
    });
  });

  function highlightStars(buttons, score, className) {
    buttons.forEach(b => {
      const bVal = parseInt(b.dataset.v, 10);
      b.classList.remove('lit', 'hover');
      if (bVal <= score) {
        b.classList.add(className);
      }
    });
  }

  /* ──────────────────────────────────────────────────────────────
     9. FORM SUBMISSION
  ────────────────────────────────────────────────────────────── */
  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideError();

    // Honeypot check
    const hp = document.getElementById('website_hp')?.value;
    if (hp && hp.trim() !== '') {
      showThankYouScreen(); // Silent pass for bot
      return;
    }

    const formData = new FormData(form);
    const data = {
      item:                formData.get('item') || '',
      overall_rating:      formData.get('overall_rating') || '',
      taste_rating:        formData.get('taste_rating') || '',
      presentation_rating: formData.get('presentation_rating') || '',
      value_rating:        formData.get('value_rating') || '',
      liked_most:          (formData.get('liked_most') || '').trim(),
      improvement:         (formData.get('improvement') || '').trim(),
      buy_again:           formData.get('buy_again') || '',
      one_word:            (formData.get('one_word') || '').trim()
    };

    if (!data.buy_again) {
      showError('Please answer if you would buy from BITE and POUR again.');
      return;
    }

    setSubmitting(true);

    try {
      // Netlify Forms: a urlencoded POST to the site root, carrying the form's name.
      const body = new URLSearchParams({ 'form-name': 'feedback', ...data });
      const res = await fetch('/', {
        method:  'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body:    body.toString()
      });
      if (res.ok) {
        showThankYouScreen();
      } else {
        showError('Could not send your review. Please try again.');
        setSubmitting(false);
      }
    } catch (err) {
      // No fake success: if it did not reach Netlify, the guest is told.
      showError('No connection — please check your internet and try again.');
      setSubmitting(false);
    }
  });

  /* ──────────────────────────────────────────────────────────────
     10. UTILITIES
  ────────────────────────────────────────────────────────────── */
  function setSubmitting(isSubmitting) {
    if (!submitBtn) return;
    submitBtn.disabled = isSubmitting;
    if (spinner) spinner.style.display = isSubmitting ? 'inline-block' : 'none';
    if (submitText) submitText.textContent = isSubmitting ? 'SAVING...' : 'SUBMIT MY REVIEW';
  }

  function showError(msg) {
    if (!errBanner || !errText) return;
    errText.textContent = msg;
    errBanner.style.display = 'flex';
    errBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function hideError() {
    if (errBanner) errBanner.style.display = 'none';
  }

  function showThankYouScreen() {
    form.style.display = 'none';
    const progress = document.querySelector('.progress-wrap');
    if (progress) progress.style.display = 'none';

    if (thankYou) {
      thankYou.style.display = 'block';
      // Force reflow so the CSS transition fires
      void thankYou.offsetWidth;
      thankYou.classList.add('show');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  // Initialize step 1
  goToStep(1);

});
