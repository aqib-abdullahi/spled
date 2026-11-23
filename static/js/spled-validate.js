(function () {
  "use strict";

  // Keep in step with the password rules in settings.py (a test checks this number).
  var MIN_PASSWORD = 10;
  // If the page has not moved on this long after a valid submit, give the button back.
  var SUBMIT_LOCK_MS = 20000;

  var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  var TEXT_TYPES = { text: 1, email: 1, search: 1, url: 1, tel: 1, textarea: 1 };
  var SKIP_TYPES = { hidden: 1, submit: 1, button: 1, reset: 1, image: 1 };
  var uid = 0;

  function esc(value) {
    return window.CSS && CSS.escape ? CSS.escape(value) : String(value).replace(/["\\]/g, "\\$&");
  }

  function labelFor(field) {
    var label = field.id ? document.querySelector('label[for="' + esc(field.id) + '"]') : null;
    if (!label) { label = field.closest("label"); }
    var text = label ? label.textContent : "";
    text = text.replace(/\s+/g, " ").replace(/\(optional\)/i, "").replace(/[*:]\s*$/, "").trim();
    return text || "This field";
  }

  function isField(el) {
    return !!(el && el.matches && el.matches("input, select, textarea") &&
      !SKIP_TYPES[(el.type || "").toLowerCase()]);
  }

  function fieldsOf(form) {
    return Array.prototype.filter.call(form.elements, function (el) {
      return isField(el) && !el.disabled;
    });
  }

  function fileMessage(field) {
    var files = field.files ? Array.prototype.slice.call(field.files) : [];
    var maxFiles = parseInt(field.getAttribute("data-max-files"), 10);
    var maxBytes = parseInt(field.getAttribute("data-max-bytes"), 10);
    if (maxFiles > 0 && files.length > maxFiles) {
      return "Choose no more than " + maxFiles + " files.";
    }
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      if (maxBytes > 0 && f.size > maxBytes) {
        return "\u201C" + f.name + "\u201D is larger than " + Math.round(maxBytes / 1048576) + " MB.";
      }
      if (/image/.test(field.accept || "") && f.type && f.type.indexOf("image/") !== 0) {
        return "\u201C" + f.name + "\u201D isn\u2019t an image.";
      }
    }
    return "";
  }

  // The message for one field, or "" if it is fine.
  function messageFor(field, form) {
    var type = (field.type || "").toLowerCase();
    var value = field.value || "";
    var name = field.name || "";
    var label = labelFor(field);
    var textual = !!TEXT_TYPES[type];
    var validity = field.validity;

    if (validity && validity.badInput) {
      return type === "date" ? "Enter a valid date." : "Enter a valid number.";
    }

    if (field.required) {
      if (type === "checkbox") {
        if (!field.checked) { return "Please tick this box to continue."; }
      } else if (type === "radio") {
        if (!form.querySelector('input[type="radio"][name="' + esc(name) + '"]:checked')) {
          return "Choose one of the options.";
        }
      } else if (type === "file") {
        if (!(field.files && field.files.length)) { return "Choose a file to upload."; }
      } else if (textual ? !value.trim() : !value) {
        return field.tagName === "SELECT" ? "Choose an option." : label + " is required.";
      }
    }

    if (type === "file") { return fileMessage(field); }
    if (type === "checkbox" || type === "radio" || !value) { return ""; }

    var newPassword = /(^|_)password1$/.test(name);
    var min = field.minLength > 0 ? field.minLength : (newPassword ? MIN_PASSWORD : 0);
    if (min && value.length < min) {
      return "Use at least " + min + " characters. You have " + value.length + ".";
    }
    if (field.maxLength > 0 && value.length > field.maxLength) {
      return "Use no more than " + field.maxLength + " characters.";
    }
    if (type === "email") {
      var lenient = name === "username"; // sign-in: do not lock out an unusual existing address
      var bad = lenient ? validity.typeMismatch : !EMAIL.test(value.trim());
      if (bad) { return "Enter a valid email address, like name@example.com."; }
    }
    if (type === "url" && validity.typeMismatch) {
      return "Enter a full web address, starting with https://";
    }
    if (newPassword && /^\d+$/.test(value)) { return "Use more than just numbers."; }
    if (/(^|_)password2$/.test(name)) {
      var other = form.elements[name.replace(/password2$/, "password1")];
      if (other && other.value !== value) { return "The two passwords don\u2019t match."; }
    }
    if (validity.rangeUnderflow) {
      return type === "date" ? "Choose a date on or after " + field.min + "." : "Enter " + field.min + " or more.";
    }
    if (validity.rangeOverflow) {
      return type === "date" ? "Choose a date on or before " + field.max + "." : "Enter " + field.max + " or less.";
    }
    if (validity.stepMismatch) { return "Enter a valid number."; }
    if (validity.patternMismatch) {
      return field.title || "Check the format of " + label.toLowerCase() + ".";
    }
    return "";
  }

  function wrapperOf(field) {
    return field.closest(".field") || field.parentNode;
  }

  function noteFor(field, create) {
    var wrapper = wrapperOf(field);
    var key = field.name || field.id || "field";
    var note = wrapper.querySelector('small[data-client-error][data-for="' + esc(key) + '"]');
    if (!note && create) {
      note = document.createElement("small");
      note.className = "field-error";
      note.setAttribute("role", "alert");
      note.setAttribute("data-client-error", "");
      note.setAttribute("data-for", key);
      note.id = "client-error-" + (++uid);
      wrapper.appendChild(note);
    }
    return note;
  }

  function show(field, message) {
    var note = noteFor(field, !!message);
    var ids = (field.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
    if (!message) {
      if (note) {
        ids = ids.filter(function (id) { return id !== note.id; });
        note.remove();
      }
      field.removeAttribute("aria-invalid");
    } else {
      note.textContent = message;
      if (ids.indexOf(note.id) === -1) { ids.push(note.id); }
      field.setAttribute("aria-invalid", "true");
    }
    if (ids.length) { field.setAttribute("aria-describedby", ids.join(" ")); }
    else { field.removeAttribute("aria-describedby"); }
  }

  // Returns true if the field is invalid, and shows the message.
  function check(field) {
    var message = messageFor(field, field.form);
    show(field, message);
    return !!message;
  }

  function clearServerError(field) {
    wrapperOf(field).querySelectorAll("small.field-error:not([data-client-error])").forEach(function (n) {
      n.remove();
    });
  }

  function focusField(field) {
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    try { field.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" }); } catch (err) { /* old browser */ }
    field.focus({ preventScroll: true });
  }

  // ---- The loading state: a ring replaces the label once a form passes validation ----

  function unlock(form) {
    clearTimeout(form.__spledTimer);
    form.removeAttribute("data-locked");
    form.removeAttribute("aria-busy");
    var button = form.__spledButton;
    if (button) {
      button.classList.remove("is-loading");
      button.removeAttribute("aria-disabled");
      button.style.removeProperty("--spinner-color");
      var note = button.querySelector("[data-loading-note]");
      if (note) { note.remove(); }
    }
    form.__spledButton = null;
  }

  function lock(form, button) {
    form.setAttribute("data-locked", "1");
    form.setAttribute("aria-busy", "true");
    form.__spledButton = null;
    // Only a real <button> can show the ring. It is never set to "disabled": a disabled
    // submit button drops its name and value from what the browser sends.
    if (button && button.tagName === "BUTTON") {
      button.style.setProperty("--spinner-color", getComputedStyle(button).color);
      button.classList.add("is-loading");
      button.setAttribute("aria-disabled", "true");
      var note = document.createElement("span");
      note.setAttribute("data-loading-note", "");
      note.setAttribute("role", "status");
      note.textContent = "Please wait";
      button.appendChild(note);
      form.__spledButton = button;
    }
    clearTimeout(form.__spledTimer);
    form.__spledTimer = setTimeout(function () { unlock(form); }, SUBMIT_LOCK_MS);
  }

  function setup(form) {
    // Messages appear only when the button is pressed. After that, a field that is showing
    // a message is checked again as it is fixed, so the message clears.
    function recheck(e) {
      var f = e.target;
      if (!isField(f)) { return; }
      clearServerError(f);
      var type = (f.type || "").toLowerCase();
      if (type === "radio" && f.name) {
        form.querySelectorAll('input[type="radio"][name="' + esc(f.name) + '"]').forEach(function (r) {
          if (r.getAttribute("aria-invalid") === "true") { check(r); }
        });
      } else if (f.getAttribute("aria-invalid") === "true") {
        check(f);
      }
      if (/(^|_)password1$/.test(f.name || "")) {
        var again = form.elements[f.name.replace(/password1$/, "password2")];
        if (again && again.getAttribute("aria-invalid") === "true") { check(again); }
      }
    }
    form.addEventListener("input", recheck);
    form.addEventListener("change", recheck);

    form.addEventListener("submit", function (e) {
      if (e.defaultPrevented) { return; }
      if (e.submitter && e.submitter.hasAttribute("formnovalidate")) { return; }
      if (form.getAttribute("data-locked")) { e.preventDefault(); return; }

      var first = null;
      fieldsOf(form).forEach(function (f) {
        if (check(f) && !first) { first = f; }
      });
      if (first) {
        e.preventDefault();
        focusField(first);
        return;
      }
      // Downloads and new-tab forms never leave the page, so a ring would spin forever.
      if (form.hasAttribute("data-allow-repeat")) { return; }
      var target = (e.submitter && e.submitter.getAttribute("formtarget")) || form.getAttribute("target");
      if (target && target !== "_self") { return; }
      var button = e.submitter || form.querySelector('button[type="submit"], button:not([type])');
      // Another handler (the map's boundary check) may still cancel this submit.
      setTimeout(function () { if (!e.defaultPrevented) { lock(form, button); } }, 0);
    });
  }

  function init() {
    var forms = Array.prototype.slice.call(
      document.querySelectorAll("form[novalidate]:not([data-no-validate])")
    );
    forms.forEach(setup);
    // Coming back with the Back button must not leave a form spinning.
    window.addEventListener("pageshow", function (e) {
      if (e.persisted) { forms.forEach(unlock); }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();