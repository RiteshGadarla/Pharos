import { useRef, useState } from 'react';
import { ArrowRight, Play, VolumeX, Waves } from 'lucide-react';

import './landing.css';

const STEPS = [
  {
    number: '01',
    title: 'SATELLITE DETECTION',
    copy: 'Analyze SAR imagery to detect oil slicks across vast ocean areas.',
  },
  {
    number: '02',
    title: 'OCEAN ANALYSIS',
    copy: 'Model wind and currents to trace the origin.',
  },
  {
    number: '03',
    title: 'VESSEL CORRELATION',
    copy: 'Reconstruct vessel activity using AIS and radar data.',
  },
  {
    number: '04',
    title: 'EVIDENCE & INSIGHTS',
    copy: 'Deliver explainable evidence to support investigations.',
  },
];

function IntelligencePanel() {
  return (
    <aside className="intel-panel">
      <div className="panel-rule" />
      <h2>FROM OBSERVATION TO EVIDENCE</h2>
      <p className="panel-intro">Turning satellite data into actionable intelligence</p>

      <div className="intel-items">
        {STEPS.map((step) => (
          <div className="intel-item" key={step.number}>
            <div className="intel-number">{step.number}</div>
            <div className="intel-content">
              <b>{step.title}</b>
              <p>{step.copy}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="progress-line">
        <span />
        <span />
        <span />
        <span />
      </div>
      <div className="progress-labels">
        <b>DETECTION</b>
        <b>ORIGIN</b>
        <b>CORRELATION</b>
        <b>EVIDENCE</b>
      </div>
    </aside>
  );
}

export default function Landing() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [soundOn, setSoundOn] = useState(false);

  // The background loop is the overview. It autoplays muted, which is all
  // a browser allows without a click; this button is that click, and
  // replays it from the start with sound, or mutes it again.
  const toggleOverview = async () => {
    const video = videoRef.current;
    if (!video) return;

    if (soundOn) {
      video.muted = true;
      setSoundOn(false);
      return;
    }

    try {
      video.currentTime = 0;
      video.muted = false;
      await video.play();
      setSoundOn(true);
    } catch (error) {
      console.error('Unable to play the overview with sound:', error);
      video.muted = true;
    }
  };

  return (
    <main className="dashboard">
      <video ref={videoRef} className="bg-video" autoPlay loop muted playsInline preload="auto">
        <source src="/landing-background.mp4" type="video/mp4" />
      </video>
      <div className="video-overlay" />

      <section className="hero">
        <div className="hero-brand">
          <Waves className="hero-brand-mark" size={46} strokeWidth={1.4} aria-hidden="true" />
          <div className="hero-brand-text">
            <strong>DRISHTA</strong>
            <span>MARITIME INTELLIGENCE</span>
          </div>
        </div>

        <p className="eyebrow">CLEANER OCEANS. SAFER TOMORROWS.</p>
        <h1>
          SEE THE SPILL.
          <br />
          TRACE THE ORIGIN.
          <br />
          IDENTIFY <em>THE VESSEL.</em>
        </h1>
        <p className="tagline">Satellite intelligence + ocean drift modelling + AIS correlation</p>

        <div className="hero-actions">
          {/* A plain link, not client-side routing: the console's
              stylesheet shares class names with this page, so /run
              gets a fresh document with only its own CSS loaded. */}
          <a href="/run" className="primary-button">
            OPEN INVESTIGATION
            <ArrowRight size={16} strokeWidth={1.8} />
          </a>

          <button type="button" className="secondary-button" onClick={toggleOverview} aria-pressed={soundOn}>
            {soundOn ? <VolumeX size={14} /> : <Play size={14} fill="currentColor" />}
            {soundOn ? 'MUTE OVERVIEW' : 'WATCH OVERVIEW'}
          </button>
        </div>
      </section>

      <IntelligencePanel />

      {/* Covers the generator's watermark in the corner of the video. */}
      <div className="video-credit">
        <div className="video-credit-line" />
        <div className="video-credit-content">
          <span>DRISHTA</span>
          <small>EARTH OBSERVATION SYSTEM</small>
        </div>
      </div>

      <footer className="bottombar">
        <div className="footer-left">
          <b>
            <Waves size={13} strokeWidth={1.8} aria-hidden="true" />
            DRISHTA
          </b>
          <span />
          <small>MARITIME INTELLIGENCE FOR A CLEANER, SAFER OCEAN</small>
        </div>

        <div className="powered">
          <i />
          <span>POWERED BY EARTH OBSERVATION. FOR A SAFER TOMORROW.</span>
        </div>
      </footer>
    </main>
  );
}
