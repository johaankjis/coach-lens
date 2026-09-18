import CommandCenter from "./command-center";

/**
 * Home opens on the backend's first observed signal. `?signal=<id>` selects another one, so a
 * link back from Training, Role-Play, or Agent Insights lands on the insight it came from.
 */
export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const requested = params.signal;
  return <CommandCenter initialSignalId={typeof requested === "string" && requested ? requested : null} />;
}
