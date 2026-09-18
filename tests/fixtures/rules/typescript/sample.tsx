export const Comp = () => <div>hi</div>;
export function Button(): JSX.Element { return <button/>; }
export default React.memo(Comp);
export class Widget extends React.Component<Props> {}

function Local() {
  const x = <span/>;
  return x;
}
