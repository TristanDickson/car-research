import Link from "next/link";

export default function NotFound() {
  return (
    <div className="py-16 text-center">
      <h1 className="text-xl font-semibold">Not found</h1>
      <p className="mt-2 text-sm text-gray-400">
        <Link href="/" className="underline">Back to the overview</Link>
      </p>
    </div>
  );
}
