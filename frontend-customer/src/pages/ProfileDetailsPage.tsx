import { useMemo, useState, type FormEvent } from 'react';
import { ApiError, api } from '../services/api';
import { useAppStore } from '../hooks/useAppStore';

interface ProfileDetailsPageProps {
  token: string | null;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

export function ProfileDetailsPage({ token, onNavigate, onToast }: ProfileDetailsPageProps) {
  const { user, updateUser } = useAppStore();
  const [fullName, setFullName] = useState(user?.full_name ?? '');
  const [phoneNumber, setPhoneNumber] = useState(user?.phone_number ?? '');
  const [defaultAddress, setDefaultAddress] = useState(user?.default_address ?? '');
  const [isSaving, setIsSaving] = useState(false);

  const joinedOn = useMemo(() => {
    if (!user) {
      return '';
    }

    return new Intl.DateTimeFormat('en-IN', {
      dateStyle: 'medium',
    }).format(new Date(user.created_at));
  }, [user]);

  if (!token || !user) {
    return (
      <div className="page-stack">
        <section className="hero-panel hero-panel--compact">
          <div className="hero-panel__copy">
            <span className="eyebrow">Profile details</span>
            <h1>Login to manage your details.</h1>
            <p>Save your name, phone number, and delivery address so checkout feels faster next time.</p>
            <div className="hero-panel__actions">
              <button className="primary-button" onClick={() => onNavigate('/auth/login')} type="button">
                Login
              </button>
              <button className="secondary-button" onClick={() => onNavigate('/auth/register')} type="button">
                Create account
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedName = fullName.trim();
    if (trimmedName.length < 2) {
      onToast('Name required', 'Please enter at least 2 characters for your name.', 'error');
      return;
    }

    setIsSaving(true);

    void api
      .updateProfile(token, {
        full_name: trimmedName,
        phone_number: phoneNumber.trim() || null,
        default_address: defaultAddress.trim() || null,
      })
      .then((updatedUser) => {
        updateUser(updatedUser);
        onToast('Profile updated', 'Your details are now saved to your account.', 'success');
        onNavigate('/profile');
      })
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.message : 'Unable to save your profile right now.';
        onToast('Save failed', message, 'error');
      })
      .finally(() => {
        setIsSaving(false);
      });
  };

  return (
    <div className="page-stack">
      <section className="hero-panel hero-panel--compact">
        <div className="hero-panel__copy">
          <span className="eyebrow">User details</span>
          <h1>Keep delivery details ready.</h1>
          <p>Update your name, contact number, and saved address so your next order feels instant.</p>
          <div className="profile-subnav">
            <button className="secondary-button" onClick={() => onNavigate('/profile')} type="button">
              Back to profile
            </button>
            <div className="profile-meta-pill">Joined {joinedOn}</div>
          </div>
        </div>
      </section>

      <section className="profile-detail-grid">
        <article className="section-card">
          <div className="section-card__header">
            <div>
              <span className="eyebrow">Edit details</span>
              <h2>Your account info</h2>
            </div>
          </div>
          <form className="profile-form" onSubmit={handleSubmit}>
            <label className="form-field">
              <span>Full name</span>
              <input
                autoComplete="name"
                onChange={(event) => setFullName(event.target.value)}
                placeholder="Enter your name"
                value={fullName}
              />
            </label>
            <label className="form-field">
              <span>Email</span>
              <input disabled readOnly value={user.email} />
            </label>
            <label className="form-field">
              <span>Phone number</span>
              <input
                autoComplete="tel"
                onChange={(event) => setPhoneNumber(event.target.value)}
                placeholder="Add your phone number"
                value={phoneNumber}
              />
            </label>
            <label className="form-field profile-form__full">
              <span>Default address</span>
              <textarea
                onChange={(event) => setDefaultAddress(event.target.value)}
                placeholder="Add your preferred delivery address"
                value={defaultAddress}
              />
            </label>
            <div className="profile-form__actions profile-form__full">
              <button className="secondary-button" onClick={() => onNavigate('/profile')} type="button">
                Cancel
              </button>
              <button className="primary-button" disabled={isSaving} type="submit">
                {isSaving ? 'Saving...' : 'Save details'}
              </button>
            </div>
          </form>
        </article>

        <article className="section-card">
          <div className="section-card__header">
            <div>
              <span className="eyebrow">Account snapshot</span>
              <h2>What’s synced here</h2>
            </div>
          </div>
          <div className="profile-list">
            <div className="profile-list__row"><span>Role</span><strong>Customer</strong></div>
            <div className="profile-list__row"><span>Verification</span><strong>{user.is_verified ? 'Verified' : 'Pending'}</strong></div>
            <div className="profile-list__row"><span>Phone</span><strong>{phoneNumber.trim() || 'Not added yet'}</strong></div>
            <div className="profile-list__row"><span>Address</span><strong>{defaultAddress.trim() || 'No address saved yet'}</strong></div>
          </div>
          <div className="empty-inline">
            <strong>Current note</strong>
            <span>
              Profile edits are saved to your real customer account and stay synced with checkout, mobile, and future sessions.
            </span>
          </div>
        </article>
      </section>
    </div>
  );
}
