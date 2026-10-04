import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="login-page">
      <div className="card empty">
        <h2>View not found</h2>
        <p>There is no StressLess view at this address.</p>
        <Link className="btn" href="/">Go to this morning</Link>
      </div>
    </div>
  );
}
