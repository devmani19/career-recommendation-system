/**
 * CareerAI - React Authentication & Credential Management System
 * Powers interactive Sign Up, Email OTP Verification, Registration Success,
 * Login, Forgot Password, and Reset Password views.
 */

(function () {
    'use strict';

    if (!window.React || !window.ReactDOM) {
        console.warn('React or ReactDOM not loaded. Relying on HTML fallback.');
        return;
    }

    const { useState, useEffect, useRef, createElement: h } = React;

    // Helper: calculate password strength (0-4)
    function getPasswordStrength(pwd) {
        if (!pwd) return { score: 0, length: false, lower: false, upper: false, number: false, special: false };
        const length = pwd.length >= 8;
        const lower = /[a-z]/.test(pwd);
        const upper = /[A-Z]/.test(pwd);
        const number = /\d/.test(pwd);
        const special = /[!@#$%^&*()_+\-=\[\]{}|;:'",.<>/?`~]/.test(pwd);
        let score = 0;
        if (length) score++;
        if (lower && upper) score++;
        if (number) score++;
        if (special) score++;
        return { score, length, lower, upper, number, special };
    }

    // SVG Icons
    const EyeIcon = ({ visible }) =>
        visible
            ? h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 },
                h('path', { d: 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z' }),
                h('circle', { cx: 12, cy: 12, r: 3 })
            )
            : h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 },
                h('path', { d: 'M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24' }),
                h('line', { x1: 1, y1: 1, x2: 23, y2: 23 })
            );

    const Spinner = () => h('span', { className: 'spinner-inline' });

    // ── Main Auth Component ──────────────────────────────────────────────────
    function AuthApp({ initialView, initialEmail, initialUserId, initialToken }) {
        const [view, setView] = useState(initialView || 'login');

        // Form fields
        const [fullName, setFullName] = useState('');
        const [email, setEmail] = useState(initialEmail || '');
        const [password, setPassword] = useState('');
        const [confirmPassword, setConfirmPassword] = useState('');
        const [showPassword, setShowPassword] = useState(false);
        const [showConfirmPassword, setShowConfirmPassword] = useState(false);
        const [rememberMe, setRememberMe] = useState(false);
        const [userId, setUserId] = useState(initialUserId || '');
        const [token, setToken] = useState(initialToken || '');

        // OTP State
        const [otpDigits, setOtpDigits] = useState(['', '', '', '', '', '']);
        const [otpCooldown, setOtpCooldown] = useState(60);
        const [otpExpiry, setOtpExpiry] = useState(300);
        const [attemptsRemaining, setAttemptsRemaining] = useState(5);
        const otpInputsRef = useRef([]);

        // Status messages
        const [loading, setLoading] = useState(false);
        const [error, setError] = useState('');
        const [success, setSuccess] = useState('');

        // Timers for OTP
        useEffect(() => {
            if (view !== 'verify-otp') return;
            const timer = setInterval(() => {
                setOtpCooldown(c => (c > 0 ? c - 1 : 0));
                setOtpExpiry(e => (e > 0 ? e - 1 : 0));
            }, 1000);
            return () => clearInterval(timer);
        }, [view]);

        // Focus first OTP box when entering verify-otp view
        useEffect(() => {
            if (view === 'verify-otp' && otpInputsRef.current[0]) {
                otpInputsRef.current[0].focus();
            }
        }, [view]);

        // Password strength calculation
        const pwdStrength = getPasswordStrength(password);

        // Clear alerts on view change
        const changeView = (newView, extraData = {}) => {
            setError('');
            setSuccess('');
            if (extraData.email) setEmail(extraData.email);
            if (extraData.userId) setUserId(extraData.userId);
            if (extraData.token) setToken(extraData.token);
            setView(newView);
        };

        // ── Handler: Register ──────────────────────────────────────────────
        const handleRegisterSubmit = async (e) => {
            e.preventDefault();
            setError('');
            setSuccess('');

            if (!fullName.trim() || !email.trim() || !password || !confirmPassword) {
                setError('Please complete all fields.');
                return;
            }
            if (!pwdStrength.length || !pwdStrength.lower || !pwdStrength.upper || !pwdStrength.number || !pwdStrength.special) {
                setError('Password does not meet the complexity requirements.');
                return;
            }
            if (password !== confirmPassword) {
                setError('Passwords do not match.');
                return;
            }

            setLoading(true);
            try {
                const res = await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        full_name: fullName.trim(),
                        email: email.trim().toLowerCase(),
                        password,
                        confirm_password: confirmPassword,
                    }),
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    setOtpCooldown(60);
                    setOtpExpiry(300);
                    setAttemptsRemaining(5);
                    setOtpDigits(['', '', '', '', '', '']);
                    setSuccess('A 6-digit verification code has been sent to your email.');
                    changeView('verify-otp', { email: email.trim().toLowerCase() });
                } else {
                    setError(data.message || 'Registration failed. Please try again.');
                }
            } catch (err) {
                setError('Network error. Please check your connection and try again.');
            } finally {
                setLoading(false);
            }
        };

        // ── Handler: OTP Input Change ──────────────────────────────────────
        const handleOtpChange = (index, value) => {
            const digit = value.replace(/\D/g, '').slice(-1);
            const newDigits = [...otpDigits];
            newDigits[index] = digit;
            setOtpDigits(newDigits);

            if (digit && index < 5 && otpInputsRef.current[index + 1]) {
                otpInputsRef.current[index + 1].focus();
            }
        };

        const handleOtpKeyDown = (index, e) => {
            if (e.key === 'Backspace' && !otpDigits[index] && index > 0 && otpInputsRef.current[index - 1]) {
                otpInputsRef.current[index - 1].focus();
            }
        };

        const handleOtpPaste = (e) => {
            e.preventDefault();
            const pasteData = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
            if (pasteData) {
                const newDigits = ['', '', '', '', '', ''];
                for (let i = 0; i < pasteData.length; i++) {
                    newDigits[i] = pasteData[i];
                }
                setOtpDigits(newDigits);
                const focusIdx = Math.min(pasteData.length, 5);
                if (otpInputsRef.current[focusIdx]) {
                    otpInputsRef.current[focusIdx].focus();
                }
            }
        };

        // ── Handler: Verify OTP ────────────────────────────────────────────
        const handleVerifyOtpSubmit = async (e) => {
            e.preventDefault();
            setError('');
            setSuccess('');

            const otp = otpDigits.join('');
            if (otp.length !== 6) {
                setError('Please enter the complete 6-digit verification code.');
                return;
            }

            setLoading(true);
            try {
                const res = await fetch('/api/auth/verify-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, otp }),
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    changeView('registration-success', {
                        email: data.login_id,
                        userId: data.user_id,
                    });
                } else {
                    if (data.attempts_remaining !== undefined) {
                        setAttemptsRemaining(data.attempts_remaining);
                    }
                    setError(data.message || 'Verification failed.');
                }
            } catch (err) {
                setError('Network error during verification. Please try again.');
            } finally {
                setLoading(false);
            }
        };

        // ── Handler: Resend OTP ────────────────────────────────────────────
        const handleResendOtp = async () => {
            if (otpCooldown > 0) return;
            setError('');
            setSuccess('');
            setLoading(true);
            try {
                const res = await fetch('/api/auth/resend-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email }),
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    setOtpCooldown(60);
                    setOtpExpiry(300);
                    setAttemptsRemaining(5);
                    setOtpDigits(['', '', '', '', '', '']);
                    setSuccess('A new verification code has been sent to your email.');
                } else {
                    setError(data.message || 'Unable to resend OTP.');
                    if (data.cooldown_seconds) setOtpCooldown(data.cooldown_seconds);
                }
            } catch (err) {
                setError('Network error while resending code.');
            } finally {
                setLoading(false);
            }
        };

        // ── Handler: Login ─────────────────────────────────────────────────
        const handleLoginSubmit = async (e) => {
            e.preventDefault();
            setError('');
            setSuccess('');

            const loginId = email.trim();
            if (!loginId || !password) {
                setError('Please enter your email and password.');
                return;
            }

            setLoading(true);
            try {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        login_id: loginId,
                        password,
                        remember_me: rememberMe,
                    }),
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    window.location.href = data.redirect || '/dashboard';
                } else {
                    if (data.requires_verification) {
                        changeView('verify-otp', { email: data.email || loginId });
                        setError(data.message);
                    } else {
                        setError(data.message || 'Invalid login credentials.');
                    }
                }
            } catch (err) {
                setError('Network error while logging in.');
            } finally {
                setLoading(false);
            }
        };

        // ── Handler: Forgot Password ───────────────────────────────────────
        const handleForgotPasswordSubmit = async (e) => {
            e.preventDefault();
            setError('');
            setSuccess('');

            if (!email.trim()) {
                setError('Please enter your registered email address.');
                return;
            }

            setLoading(true);
            try {
                const res = await fetch('/api/auth/forgot-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: email.trim() }),
                });
                const data = await res.json();
                setSuccess(data.message || 'If an account exists with that email, reset instructions were sent.');
            } catch (err) {
                setError('Network error. Please try again.');
            } finally {
                setLoading(false);
            }
        };

        // ── Handler: Reset Password ────────────────────────────────────────
        const handleResetPasswordSubmit = async (e) => {
            e.preventDefault();
            setError('');
            setSuccess('');

            if (!token) {
                setError('Reset token is missing.');
                return;
            }
            if (!pwdStrength.length || !pwdStrength.lower || !pwdStrength.upper || !pwdStrength.number || !pwdStrength.special) {
                setError('New password does not meet complexity requirements.');
                return;
            }
            if (password !== confirmPassword) {
                setError('Passwords do not match.');
                return;
            }

            setLoading(true);
            try {
                const res = await fetch('/api/auth/reset-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        token,
                        password,
                        confirm_password: confirmPassword,
                    }),
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    changeView('login');
                    setSuccess('Password reset successfully! Please log in with your new password.');
                    setPassword('');
                    setConfirmPassword('');
                } else {
                    setError(data.message || 'Failed to reset password.');
                }
            } catch (err) {
                setError('Network error while resetting password.');
            } finally {
                setLoading(false);
            }
        };

        // ── Render Helpers ─────────────────────────────────────────────────
        const renderAlerts = () =>
            h('div', null,
                error && h('div', { className: 'alert error', role: 'alert' }, error),
                success && h('div', { className: 'alert success', role: 'alert' }, success)
            );

        // ── View 1: Sign Up ────────────────────────────────────────────────
        if (view === 'register') {
            return h('div', { className: 'auth-card-content' },
                h('p', { className: 'eyebrow' }, 'Get Started'),
                h('h2', null, 'Create your account'),
                h('p', { className: 'auth-description' }, 'Register with your email to begin your AI career analysis.'),
                renderAlerts(),
                h('form', { className: 'auth-form', onSubmit: handleRegisterSubmit },
                    h('label', { htmlFor: 'react-full-name' }, 'Full name'),
                    h('input', {
                        id: 'react-full-name',
                        type: 'text',
                        placeholder: 'Jane Doe',
                        value: fullName,
                        onChange: (e) => setFullName(e.target.value),
                        required: true,
                        autoFocus: true,
                    }),

                    h('label', { htmlFor: 'react-email' }, 'Email address (Login ID)'),
                    h('input', {
                        id: 'react-email',
                        type: 'email',
                        placeholder: 'you@example.com',
                        value: email,
                        onChange: (e) => setEmail(e.target.value),
                        required: true,
                    }),

                    h('label', { htmlFor: 'react-password' }, 'Password'),
                    h('div', { className: 'password-input-wrapper' },
                        h('input', {
                            id: 'react-password',
                            type: showPassword ? 'text' : 'password',
                            placeholder: 'Create a strong password',
                            value: password,
                            onChange: (e) => setPassword(e.target.value),
                            required: true,
                        }),
                        h('button', {
                            type: 'button',
                            className: 'password-toggle-btn',
                            onClick: () => setShowPassword(!showPassword),
                            'aria-label': showPassword ? 'Hide password' : 'Show password',
                        }, h(EyeIcon, { visible: showPassword }))
                    ),

                    // Password strength meter
                    password && h('div', { className: 'password-strength-wrap' },
                        h('div', { className: 'password-strength-bar' },
                            [1, 2, 3, 4].map((step) => {
                                const activeClass =
                                    pwdStrength.score >= step
                                        ? pwdStrength.score <= 1
                                            ? 'active-weak'
                                            : pwdStrength.score === 2
                                                ? 'active-fair'
                                                : pwdStrength.score === 3
                                                    ? 'active-good'
                                                    : 'active-strong'
                                        : '';
                                return h('div', { key: step, className: `password-strength-segment ${activeClass}` });
                            })
                        ),
                        h('div', { className: 'password-rules' },
                            h('div', { className: `password-rule-item ${pwdStrength.length ? 'valid' : ''}` },
                                h('span', { className: 'icon' }, pwdStrength.length ? '✓' : '•'),
                                '8+ characters'
                            ),
                            h('div', { className: `password-rule-item ${pwdStrength.upper && pwdStrength.lower ? 'valid' : ''}` },
                                h('span', { className: 'icon' }, pwdStrength.upper && pwdStrength.lower ? '✓' : '•'),
                                'Uppercase & lowercase'
                            ),
                            h('div', { className: `password-rule-item ${pwdStrength.number ? 'valid' : ''}` },
                                h('span', { className: 'icon' }, pwdStrength.number ? '✓' : '•'),
                                'At least 1 number'
                            ),
                            h('div', { className: `password-rule-item ${pwdStrength.special ? 'valid' : ''}` },
                                h('span', { className: 'icon' }, pwdStrength.special ? '✓' : '•'),
                                'At least 1 symbol'
                            )
                        )
                    ),

                    h('label', { htmlFor: 'react-confirm-password' }, 'Confirm password'),
                    h('div', { className: 'password-input-wrapper' },
                        h('input', {
                            id: 'react-confirm-password',
                            type: showConfirmPassword ? 'text' : 'password',
                            placeholder: 'Re-enter your password',
                            value: confirmPassword,
                            onChange: (e) => setConfirmPassword(e.target.value),
                            required: true,
                        }),
                        h('button', {
                            type: 'button',
                            className: 'password-toggle-btn',
                            onClick: () => setShowConfirmPassword(!showConfirmPassword),
                            'aria-label': showConfirmPassword ? 'Hide password' : 'Show password',
                        }, h(EyeIcon, { visible: showConfirmPassword }))
                    ),

                    h('button', { type: 'submit', disabled: loading },
                        loading ? [h(Spinner, { key: 's' }), 'Creating account...'] : [
                            h('span', { key: 't' }, 'Create Account & Send Code'),
                            h('span', { key: 'a', 'aria-hidden': 'true' }, '→'),
                        ]
                    )
                ),
                h('p', { className: 'auth-link' },
                    'Already have an account? ',
                    h('a', {
                        href: '#',
                        onClick: (e) => { e.preventDefault(); changeView('login'); },
                    }, 'Log in')
                )
            );
        }

        // ── View 2: Email OTP Verification ─────────────────────────────────
        if (view === 'verify-otp') {
            const formatTime = (secs) => {
                const m = Math.floor(secs / 60);
                const s = secs % 60;
                return `${m}:${s < 10 ? '0' : ''}${s}`;
            };

            return h('div', { className: 'auth-card-content' },
                h('p', { className: 'eyebrow' }, 'Security Verification'),
                h('h2', null, 'Verify your email'),
                h('p', { className: 'auth-description' },
                    'Enter the 6-digit verification code sent to ',
                    h('strong', null, email),
                    '.'
                ),
                renderAlerts(),
                h('form', { className: 'auth-form', onSubmit: handleVerifyOtpSubmit },
                    h('div', { className: 'otp-container' },
                        h('div', { className: 'otp-box-row' },
                            otpDigits.map((digit, idx) =>
                                h('input', {
                                    key: idx,
                                    ref: (el) => (otpInputsRef.current[idx] = el),
                                    className: 'otp-box-input',
                                    type: 'text',
                                    inputMode: 'numeric',
                                    maxLength: 1,
                                    value: digit,
                                    onChange: (e) => handleOtpChange(idx, e.target.value),
                                    onKeyDown: (e) => handleOtpKeyDown(idx, e),
                                    onPaste: handleOtpPaste,
                                    autoFocus: idx === 0,
                                })
                            )
                        ),
                        h('div', { className: 'otp-meta' },
                            h('span', { className: `timer-pill ${otpExpiry < 60 ? 'urgent' : ''}` },
                                'Expires in ',
                                formatTime(otpExpiry)
                            ),
                            h('span', null, `Attempts remaining: ${attemptsRemaining}`)
                        )
                    ),

                    h('button', { type: 'submit', disabled: loading || otpExpiry <= 0 },
                        loading ? [h(Spinner, { key: 's' }), 'Verifying code...'] : [
                            h('span', { key: 't' }, 'Verify & Activate Account'),
                            h('span', { key: 'a', 'aria-hidden': 'true' }, '✓'),
                        ]
                    ),

                    h('div', { style: { marginTop: 14, textAlign: 'center', fontSize: '0.75rem' } },
                        otpCooldown > 0
                            ? h('span', { style: { color: 'var(--muted)' } }, `Resend code in ${otpCooldown}s`)
                            : h('button', {
                                type: 'button',
                                className: 'resend-link-btn',
                                onClick: handleResendOtp,
                                disabled: loading,
                            }, 'Resend Verification Code')
                    )
                ),
                h('p', { className: 'auth-link' },
                    'Wrong email address? ',
                    h('a', {
                        href: '#',
                        onClick: (e) => { e.preventDefault(); changeView('register'); },
                    }, 'Register again')
                )
            );
        }

        // ── View 3: Registration Success ───────────────────────────────────
        if (view === 'registration-success') {
            return h('div', { className: 'auth-card-content' },
                h('p', { className: 'eyebrow' }, 'Account Activated'),
                h('h2', null, 'Registration Successful!'),
                h('p', { className: 'auth-description' },
                    'Your email has been verified and your account is now fully active.'
                ),
                h('div', { className: 'reg-success-card' },
                    h('h3', null,
                        h('span', { style: { color: 'var(--teal)' } }, '✓'),
                        'Your Official Login Details'
                    ),
                    h('div', { className: 'reg-detail-row' },
                        h('span', { className: 'reg-detail-label' }, 'Login ID:'),
                        h('span', { className: 'reg-detail-value' }, email)
                    ),
                    h('div', { className: 'reg-detail-row' },
                        h('span', { className: 'reg-detail-label' }, 'Account ID:'),
                        h('span', { className: 'reg-detail-value' }, userId || 'Generated')
                    ),
                    h('div', { className: 'reg-detail-row' },
                        h('span', { className: 'reg-detail-label' }, 'Password:'),
                        h('span', { style: { fontSize: '0.78rem', color: 'var(--muted)' } },
                            'Use the password you created during registration.'
                        )
                    )
                ),
                h('p', { style: { fontSize: '0.75rem', color: 'var(--muted)', margin: '12px 0 16px' } },
                    'A confirmation email containing your Login ID and account details has been sent to your verified email address.'
                ),
                h('button', {
                    type: 'button',
                    style: { width: '100%' },
                    onClick: () => changeView('login'),
                },
                    h('span', null, 'Proceed to Log In'),
                    h('span', { 'aria-hidden': 'true' }, '→')
                )
            );
        }

        // ── View 4: Login ──────────────────────────────────────────────────
        if (view === 'login') {
            return h('div', { className: 'auth-card-content' },
                h('p', { className: 'eyebrow' }, 'Welcome Back'),
                h('h2', null, 'Log in to your account'),
                h('p', { className: 'auth-description' }, 'Use your registered email address (Login ID) to continue.'),
                renderAlerts(),
                h('form', { className: 'auth-form', onSubmit: handleLoginSubmit },
                    h('label', { htmlFor: 'react-login-id' }, 'Login ID / Email address'),
                    h('input', {
                        id: 'react-login-id',
                        type: 'text',
                        placeholder: 'you@example.com',
                        value: email,
                        onChange: (e) => setEmail(e.target.value),
                        required: true,
                        autoFocus: true,
                    }),

                    h('label', { htmlFor: 'react-login-password' }, 'Password'),
                    h('div', { className: 'password-input-wrapper' },
                        h('input', {
                            id: 'react-login-password',
                            type: showPassword ? 'text' : 'password',
                            placeholder: 'Enter your password',
                            value: password,
                            onChange: (e) => setPassword(e.target.value),
                            required: true,
                        }),
                        h('button', {
                            type: 'button',
                            className: 'password-toggle-btn',
                            onClick: () => setShowPassword(!showPassword),
                            'aria-label': showPassword ? 'Hide password' : 'Show password',
                        }, h(EyeIcon, { visible: showPassword }))
                    ),

                    h('div', { className: 'auth-checkbox-row' },
                        h('label', { className: 'auth-checkbox-label' },
                            h('input', {
                                type: 'checkbox',
                                checked: rememberMe,
                                onChange: (e) => setRememberMe(e.target.checked),
                            }),
                            'Remember me'
                        ),
                        h('a', {
                            href: '#',
                            className: 'auth-forgot-link',
                            onClick: (e) => { e.preventDefault(); changeView('forgot-password'); },
                        }, 'Forgot password?')
                    ),

                    h('button', { type: 'submit', disabled: loading },
                        loading ? [h(Spinner, { key: 's' }), 'Logging in...'] : [
                            h('span', { key: 't' }, 'Log In'),
                            h('span', { key: 'a', 'aria-hidden': 'true' }, '→'),
                        ]
                    )
                ),
                h('p', { className: 'auth-link' },
                    'New to CareerAI? ',
                    h('a', {
                        href: '#',
                        onClick: (e) => { e.preventDefault(); changeView('register'); },
                    }, 'Create an account')
                )
            );
        }

        // ── View 5: Forgot Password ────────────────────────────────────────
        if (view === 'forgot-password') {
            return h('div', { className: 'auth-card-content' },
                h('p', { className: 'eyebrow' }, 'Account Recovery'),
                h('h2', null, 'Forgot your password?'),
                h('p', { className: 'auth-description' },
                    'Enter your registered email address and we will send you a secure link to reset your password.'
                ),
                renderAlerts(),
                h('form', { className: 'auth-form', onSubmit: handleForgotPasswordSubmit },
                    h('label', { htmlFor: 'react-forgot-email' }, 'Registered Email address'),
                    h('input', {
                        id: 'react-forgot-email',
                        type: 'email',
                        placeholder: 'you@example.com',
                        value: email,
                        onChange: (e) => setEmail(e.target.value),
                        required: true,
                        autoFocus: true,
                    }),

                    h('button', { type: 'submit', disabled: loading },
                        loading ? [h(Spinner, { key: 's' }), 'Sending link...'] : [
                            h('span', { key: 't' }, 'Send Reset Link'),
                            h('span', { key: 'a', 'aria-hidden': 'true' }, '→'),
                        ]
                    )
                ),
                h('p', { className: 'auth-link' },
                    'Remember your password? ',
                    h('a', {
                        href: '#',
                        onClick: (e) => { e.preventDefault(); changeView('login'); },
                    }, 'Back to log in')
                )
            );
        }

        // ── View 6: Reset Password ─────────────────────────────────────────
        if (view === 'reset-password') {
            return h('div', { className: 'auth-card-content' },
                h('p', { className: 'eyebrow' }, 'Set New Password'),
                h('h2', null, 'Reset your password'),
                h('p', { className: 'auth-description' }, 'Create a strong, new password for your CareerAI account.'),
                renderAlerts(),
                h('form', { className: 'auth-form', onSubmit: handleResetPasswordSubmit },
                    h('label', { htmlFor: 'react-reset-password' }, 'New Password'),
                    h('div', { className: 'password-input-wrapper' },
                        h('input', {
                            id: 'react-reset-password',
                            type: showPassword ? 'text' : 'password',
                            placeholder: 'Create a strong new password',
                            value: password,
                            onChange: (e) => setPassword(e.target.value),
                            required: true,
                            autoFocus: true,
                        }),
                        h('button', {
                            type: 'button',
                            className: 'password-toggle-btn',
                            onClick: () => setShowPassword(!showPassword),
                            'aria-label': showPassword ? 'Hide password' : 'Show password',
                        }, h(EyeIcon, { visible: showPassword }))
                    ),

                    password && h('div', { className: 'password-strength-wrap' },
                        h('div', { className: 'password-strength-bar' },
                            [1, 2, 3, 4].map((step) => {
                                const activeClass =
                                    pwdStrength.score >= step
                                        ? pwdStrength.score <= 1
                                            ? 'active-weak'
                                            : pwdStrength.score === 2
                                                ? 'active-fair'
                                                : pwdStrength.score === 3
                                                    ? 'active-good'
                                                    : 'active-strong'
                                        : '';
                                return h('div', { key: step, className: `password-strength-segment ${activeClass}` });
                            })
                        ),
                        h('div', { className: 'password-rules' },
                            h('div', { className: `password-rule-item ${pwdStrength.length ? 'valid' : ''}` },
                                h('span', { className: 'icon' }, pwdStrength.length ? '✓' : '•'),
                                '8+ characters'
                            ),
                            h('div', { className: `password-rule-item ${pwdStrength.upper && pwdStrength.lower ? 'valid' : ''}` },
                                h('span', { className: 'icon' }, pwdStrength.upper && pwdStrength.lower ? '✓' : '•'),
                                'Uppercase & lowercase'
                            ),
                            h('div', { className: `password-rule-item ${pwdStrength.number ? 'valid' : ''}` },
                                h('span', { className: 'icon' }, pwdStrength.number ? '✓' : '•'),
                                'At least 1 number'
                            ),
                            h('div', { className: `password-rule-item ${pwdStrength.special ? 'valid' : ''}` },
                                h('span', { className: 'icon' }, pwdStrength.special ? '✓' : '•'),
                                'At least 1 symbol'
                            )
                        )
                    ),

                    h('label', { htmlFor: 'react-reset-confirm' }, 'Confirm New Password'),
                    h('div', { className: 'password-input-wrapper' },
                        h('input', {
                            id: 'react-reset-confirm',
                            type: showConfirmPassword ? 'text' : 'password',
                            placeholder: 'Re-enter your new password',
                            value: confirmPassword,
                            onChange: (e) => setConfirmPassword(e.target.value),
                            required: true,
                        }),
                        h('button', {
                            type: 'button',
                            className: 'password-toggle-btn',
                            onClick: () => setShowConfirmPassword(!showConfirmPassword),
                            'aria-label': showConfirmPassword ? 'Hide password' : 'Show password',
                        }, h(EyeIcon, { visible: showConfirmPassword }))
                    ),

                    h('button', { type: 'submit', disabled: loading },
                        loading ? [h(Spinner, { key: 's' }), 'Resetting password...'] : [
                            h('span', { key: 't' }, 'Set New Password'),
                            h('span', { key: 'a', 'aria-hidden': 'true' }, '✓'),
                        ]
                    )
                ),
                h('p', { className: 'auth-link' },
                    h('a', {
                        href: '#',
                        onClick: (e) => { e.preventDefault(); changeView('login'); },
                    }, '← Back to log in')
                )
            );
        }

        return null;
    }

    // Auto-mount React App onto #react-auth-root
    document.addEventListener('DOMContentLoaded', () => {
        const rootEl = document.getElementById('react-auth-root');
        if (!rootEl) return;

        const urlParams = new URLSearchParams(window.location.search);
        const initialView = rootEl.getAttribute('data-initial-view') || urlParams.get('view') || 'login';
        const initialEmail = rootEl.getAttribute('data-initial-email') || urlParams.get('email') || '';
        const initialUserId = rootEl.getAttribute('data-initial-user-id') || urlParams.get('user_id') || '';
        const initialToken = rootEl.getAttribute('data-initial-token') || urlParams.get('token') || '';
        // Hide static fallback card if React successfully loads
        const staticCard = document.getElementById('static-auth-card');
        if (staticCard) {
            staticCard.style.display = 'none';
        }
        rootEl.style.display = 'block';

        const root = ReactDOM.createRoot(rootEl);
        root.render(h(AuthApp, {
            initialView,
            initialEmail,
            initialUserId,
            initialToken,
        }));
    });
})();
