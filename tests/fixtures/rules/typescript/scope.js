function notExported() {
  const local = 1;
  module.exports.sneaky = local;
  return local;
}

module.exports.Bar = 2;

export const PLAIN = 1;
