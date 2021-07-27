const webpack = require('webpack'); 
const path = require('path');

const MiniCssExtractPlugin = require('mini-css-extract-plugin');
const OptimizeCSSAssetsPlugin = require('optimize-css-assets-webpack-plugin');
const TerserPlugin = require('terser-webpack-plugin');

const INPUT_DIR = path.resolve(__dirname, './assets/src');
const OUTPUT_DIR = path.resolve(__dirname, './assets/dist');

module.exports = {
  entry: path.resolve(INPUT_DIR, 'index.js'),
  output: {
    path: OUTPUT_DIR,
    filename: 'bundle.js'
  },
  module: {
    rules: [{
        test: /\.scss$/,
        use: [
          MiniCssExtractPlugin.loader,
          'css-loader',
          'sass-loader'
        ]
    }, {
      // the file-loader emits files directly to OUTPUT_DIR/fonts
      test: /\.(woff(2)?|ttf|eot)(\?v=[0-9]\.[0-9]\.[0-9])?$/,
      loader: 'file-loader?name=./fonts/[name].[ext]',
    }, {
      // Image loader
      // the file-loader emits files directly to OUTPUT_DIR/img
      test: /\.(png|gif|jpg|jpeg|svg)$/,
      loaders: ['file-loader?name=./img/[name].[ext]']
    }]
  },
  optimization: {
    minimizer: [
      new TerserPlugin(),
      new OptimizeCSSAssetsPlugin({})
    ]
  },
  plugins: [
    new MiniCssExtractPlugin({
      // Options similar to the same options in webpackOptions.output
      filename: '[name].css',
      path: OUTPUT_DIR,
      chunkFilename: '[id].css'
    }),

    // Makes jQuery (required for bootstrap4) available to other JS includes
    // https://webpack.js.org/plugins/provide-plugin/
    new webpack.ProvidePlugin({
      $: 'jquery',
      jQuery: 'jquery',
      'window.jQuery': 'jquery'
    }),
  ]
};
