import { redirect } from 'next/navigation';

export default function CalendarConnectionCallback() {
  redirect('/calendar?sync=google');
}