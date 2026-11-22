import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import App from '../App';

describe('MuleTrace App Foundation', () => {
  it('renders MuleTrace branding and foundation title', () => {
    render(<App />);
    expect(screen.getByText('MuleTrace')).toBeInTheDocument();
    expect(screen.getByText('Foundation Initialized')).toBeInTheDocument();
  });

  it('displays collaborators Shaili and Raj', () => {
    render(<App />);
    expect(screen.getByText(/Shaili & Raj/i)).toBeInTheDocument();
  });

  it('renders technology stack sections', () => {
    render(<App />);
    expect(screen.getByText('Frontend Stack')).toBeInTheDocument();
    expect(screen.getByText('Backend Stack')).toBeInTheDocument();
    expect(screen.getByText('API & Testing')).toBeInTheDocument();
  });
});
