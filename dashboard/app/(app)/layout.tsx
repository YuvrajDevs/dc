import { Nav } from "@/components/nav";

/** The working app: a white page, navigation down the left side. */
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="mx-auto w-full max-w-[1400px] p-2 sm:p-4">
      <div className="panel relative min-h-[calc(100vh-2rem)] lg:grid lg:grid-cols-[210px_1fr] lg:gap-8">
        <Nav />
        <main id="main" className="rise min-w-0 px-1 pb-8 pt-4 sm:px-3 lg:pt-3">
          {children}
        </main>
      </div>
    </div>
  );
}
